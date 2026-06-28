from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, AsyncGenerator

from wb_parser.client import WildberriesClient
from wb_parser.config import CollectorSettings
from wb_parser.utils import format_elapsed

logger = logging.getLogger(__name__)

ProductRow = dict[str, Any]


@dataclass(frozen=True, slots=True)
class Segment:
    """Ценовой диапазон, который будет обработан за один проход."""
    min_price: int
    max_price: int
    depth: int = 0

    @property
    def span(self) -> int:
        return max(0, self.max_price - self.min_price)

    @property
    def price_u(self) -> str:
        return f"{self.min_price};{self.max_price}"


@dataclass(slots=True)
class SegmentStats:
    """Статистика по одному сегменту."""
    fetched: int = 0
    new: int = 0
    global_duplicates: int = 0
    internal_duplicates: int = 0
    errors: int = 0
    pages: int = 0
    page_budget: int = 1
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Парсинг одного товара
# ---------------------------------------------------------------------------

def _extract_price_rub(product: dict[str, Any]) -> float | None:
    for size in product.get("sizes") or []:
        pp = (size.get("price") or {}).get("product")
        if isinstance(pp, (int, float)):
            return round(int(pp) / 100, 2)
    for field in ("salePriceU", "priceU"):
        raw = product.get(field)
        if isinstance(raw, (int, float)):
            return round(float(raw) / 100, 2)
    return None


def parse_product(product: dict[str, Any]) -> ProductRow:
    """Сырой dict товара → плоский словарь для Excel."""
    pid = product.get("id")

    product_rating = None
    for field in ("nmReviewRating", "reviewRating", "rating"):
        v = product.get(field)
        if isinstance(v, (int, float)):
            product_rating = round(float(v), 2)
            break

    reviews_count = None
    for field in ("nmFeedbacks", "feedbacks"):
        v = product.get(field)
        if isinstance(v, int):
            reviews_count = v
            break

    v = product.get("supplierRating")
    seller_rating = round(float(v), 2) if isinstance(v, (int, float)) else None

    return {
        "id": pid,
        "name": product.get("name"),
        "brand": product.get("brand"),
        "store_name": product.get("supplier"),
        "product_rating": product_rating,
        "seller_rating": seller_rating,
        "reviews_count": reviews_count,
        "price_rub": _extract_price_rub(product),
        "link": f"https://www.wildberries.ru/catalog/{pid}/detail.aspx" if pid else None,
    }


# ---------------------------------------------------------------------------
# Логика обхода сегментов
# ---------------------------------------------------------------------------

def _choose_page_budget(first_page_count: int, max_pages: int) -> int:
    """Сколько страниц запрашивать в сегменте, исходя из плотности первой страницы."""
    budget = max(1, max_pages)
    if first_page_count >= 95:   # полная страница — берём все
        return budget
    if first_page_count >= 60:   # плотная — до 3 страниц
        return min(budget, 3)
    if first_page_count >= 25:   # средняя — до 2 страниц
        return min(budget, 2)
    return 1                     # мало товаров — одна страница


async def _page_plan(
    sorts: tuple[str, ...],
    page_budget: int,
    first_products: list[dict[str, Any]],
) -> AsyncGenerator[tuple[str, int, list[dict[str, Any]] | None], None]:
    """Асинхронный генератор плана обхода: (sort, page, cached_products)."""
    yield sorts[0], 1, first_products
    for page in range(2, page_budget + 1):
        yield sorts[0], page, None
    for sort in sorts[1:]:
        for page in range(1, page_budget + 1):
            yield sort, page, None


def _split_segment(segment: Segment, narrow: bool) -> list[Segment]:
    """Делит сегмент на 2 части (или 3 при narrow=True, когда много дублей)."""
    if segment.span <= 1:
        return []
    next_depth = segment.depth + 1
    if narrow and segment.span >= 3:
        step = max(1, segment.span // 3)
        left_max = min(segment.max_price, segment.min_price + step)
        mid_max = min(segment.max_price, left_max + 1 + step)
        candidates = [
            Segment(segment.min_price, left_max, next_depth),
            Segment(left_max + 1, mid_max, next_depth),
            Segment(mid_max + 1, segment.max_price, next_depth),
        ]
    else:
        middle = segment.min_price + segment.span // 2
        candidates = [
            Segment(segment.min_price, middle, next_depth),
            Segment(middle + 1, segment.max_price, next_depth),
        ]
    return [c for c in candidates if c.min_price <= c.max_price]


def _should_split(
    *,
    segment: Segment,
    stats: SegmentStats,
    target_remaining: int,
    max_depth: int,
    min_price_span: int,
    split_threshold: int,
) -> bool:
    if segment.depth >= max_depth or segment.span < min_price_span or target_remaining <= 0:
        return False
    full_pages = stats.pages >= stats.page_budget and stats.fetched >= stats.pages * 90
    dup_heavy = stats.global_duplicates + stats.internal_duplicates > stats.new
    return (
        stats.new >= split_threshold
        or (full_pages and stats.new >= max(60, split_threshold // 2))
        or (stats.new < 40 and dup_heavy)
    )


# ---------------------------------------------------------------------------
# Коллектор
# ---------------------------------------------------------------------------

class ProductCollector:
    def __init__(self, client: WildberriesClient, settings: CollectorSettings) -> None:
        self._client = client
        self._settings = settings

    async def collect(self, *, query: str) -> list[ProductRow]:
        """Обходит ценовые сегменты и собирает уникальные товары."""
        s = self._settings
        if s.price_min is not None and s.price_max is not None:
            price_min, price_max = s.price_min, s.price_max
        else:
            price_min, price_max = await self._client.fetch_price_bounds(query=query, dest=s.dest)

        queue: deque[Segment] = deque([Segment(price_min, price_max)])
        collected: list[ProductRow] = []
        seen_ids: set[int] = set()
        total_segments = total_errors = total_gdup = total_idup = 0

        while queue and len(collected) < s.target_count:
            seg = queue.popleft()
            total_segments += 1
            stats = await self._crawl_segment(
                query=query, segment=seg, seen_ids=seen_ids, collected=collected,
            )
            total_errors += stats.errors
            total_gdup += stats.global_duplicates
            total_idup += stats.internal_duplicates

            logger.info(
                "[segment] depth=%s priceU=%s new=%s dup=%s idup=%s err=%s pages=%s/%s %s total=%s",
                seg.depth, seg.price_u, stats.new, stats.global_duplicates,
                stats.internal_duplicates, stats.errors, stats.pages, stats.page_budget,
                format_elapsed(stats.elapsed_seconds), len(collected),
            )

            if _should_split(
                segment=seg, stats=stats,
                target_remaining=s.target_count - len(collected),
                max_depth=s.max_depth, min_price_span=s.min_price_span,
                split_threshold=s.split_threshold,
            ):
                narrow = stats.new < 40 and (stats.global_duplicates + stats.internal_duplicates > stats.new)
                queue.extend(_split_segment(seg, narrow=narrow))

        logger.info(
            "[summary] segments=%s errors=%s gdup=%s idup=%s",
            total_segments, total_errors, total_gdup, total_idup,
        )
        return collected

    async def _crawl_segment(
        self,
        *,
        query: str,
        segment: Segment,
        seen_ids: set[int],
        collected: list[ProductRow],
    ) -> SegmentStats:
        """Обходит все страницы одного ценового сегмента."""
        started_at = time.perf_counter()
        s = self._settings
        stats = SegmentStats()
        seg_seen: set[int] = set()

        first_products, retry_err = await self._client.fetch_products_page(
            query=query, sort=s.sorts[0], page=1, dest=s.dest,
            price_min=segment.min_price, price_max=segment.max_price,
        )
        stats.errors += retry_err
        stats.page_budget = _choose_page_budget(len(first_products), s.max_pages)

        async for sort, page, cached in _page_plan(s.sorts, stats.page_budget, first_products):
            if len(collected) >= s.target_count:
                break

            if cached is None:
                products, retry_err = await self._client.fetch_products_page(
                    query=query, sort=sort, page=page, dest=s.dest,
                    price_min=segment.min_price, price_max=segment.max_price,
                )
                stats.errors += retry_err
            else:
                products = cached

            stats.pages += 1
            if not products:
                continue

            for raw in products:
                pid = raw.get("id")
                if not isinstance(pid, int):
                    continue
                stats.fetched += 1
                if pid in seg_seen:
                    stats.internal_duplicates += 1
                    continue
                seg_seen.add(pid)
                if pid in seen_ids:
                    stats.global_duplicates += 1
                    continue
                collected.append(parse_product(raw))
                seen_ids.add(pid)
                stats.new += 1
                if len(collected) >= s.target_count:
                    break

            # Задержка между страницами — управляется через rate_limit в клиенте,
            # но если нужен дополнительный delay — await asyncio.sleep(s.delay)

        stats.elapsed_seconds = time.perf_counter() - started_at
        return stats