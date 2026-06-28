from __future__ import annotations

import asyncio
import random
from collections import deque
from datetime import UTC, datetime
from typing import Any, Iterator

import aiohttp

from wb_parser.config import ApiCredentials, WB_MENU_URL, WB_SEARCH_URL
from wb_parser.utils import normalize_url, parse_search_query_from_url
from urllib.parse import urlparse


def _make_query_id(wb_uid: str) -> str:
    """Формирует уникальный queryid с миллисекундами и случайным числом."""
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")[:-3]  # миллисекунды
    rand_suffix = random.randint(100, 999)
    return f"qid{wb_uid}{timestamp}{rand_suffix}"


def _build_params(
    *,
    query: str,
    resultset: str,
    sort: str = "popular",
    page: int = 1,
    dest: str,
    price_min: int | None = None,
    price_max: int | None = None,
) -> dict[str, str]:
    params: dict[str, str] = {
        "ab_testing": "false",
        "appType": "1",
        "curr": "rub",
        "dest": dest,
        "hide_vflags": "4294967296",
        "lang": "ru",
        "query": query,
        "resultset": resultset,
        "sort": sort,
        "spp": "30",
        "suppressSpellcheck": "false",
    }
    if resultset == "catalog":
        params["page"] = str(page)
    if price_min is not None and price_max is not None:
        params["priceU"] = f"{price_min};{price_max}"
    return params


def _extract_raw_prices(products: list[dict[str, Any]]) -> list[int]:
    prices: list[int] = []
    for p in products:
        for size in p.get("sizes") or []:
            pp = (size.get("price") or {}).get("product")
            if isinstance(pp, (int, float)):
                prices.append(int(pp))
        for field in ("salePriceU", "priceU"):
            raw = p.get(field)
            if isinstance(raw, (int, float)):
                prices.append(int(raw))
    return prices


def _jitter(base: float, spread: float = 0.5) -> float:
    return base * (1 + random.uniform(-spread, spread))


class WildberriesClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        credentials: ApiCredentials,
        referer: str,
        timeout: int,
        rate_limit: float = 1.0,
        extra_cookies: dict[str, str] | None = None,   # все куки из cookies.txt
    ) -> None:
        self._session = session
        self._credentials = credentials
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._rate_limit = rate_limit
        self._last_request_at: float = 0.0

        # Базовые заголовки (добавлен x-wbaas-token и origin)
        self._base_headers = {
            "accept": "*/*",
            "accept-language": "ru,en;q=0.9",
            "deviceid": credentials.device_id,
            "referer": referer,
            "origin": "https://www.wildberries.ru",          # новый заголовок
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/146.0.0.0 Safari/537.36"
            ),
            "x-requested-with": "XMLHttpRequest",
            "x-spa-version": "14.3.2",
            "x-userid": "0",
            "x-wbaas-token": credentials.x_wbaas_token,     # токен в заголовке
        }

        # Формируем словарь всех кук
        all_cookies = {
            "x_wbaas_token": credentials.x_wbaas_token,
            "_wbauid": credentials.wb_uid,
        }
        if extra_cookies:
            all_cookies.update(extra_cookies)
        self._cookies = all_cookies

        # Устанавливаем куки в сессию, чтобы они отправлялись автоматически
        self._session.cookie_jar.update_cookies(all_cookies)

    async def _throttle(self) -> None:
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_at
        wait = _jitter(self._rate_limit) - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request_at = asyncio.get_event_loop().time()

    async def _request_json(self, *, params: dict[str, str], retries: int = 3) -> tuple[dict[str, Any], int]:
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            await self._throttle()
            try:
                headers = {
                    **self._base_headers,
                    "x-queryid": _make_query_id(self._credentials.wb_uid),
                }
                # Куки уже в сессии, но можно дополнительно передать в запросе (для надёжности)
                async with self._session.get(
                    WB_SEARCH_URL,
                    params=params,
                    headers=headers,
                    timeout=self._timeout,
                ) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
                    if not isinstance(payload, dict):
                        raise RuntimeError("WB search API вернул неожиданный формат JSON.")
                    return payload, attempt - 1
            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    await asyncio.sleep(_jitter(2 ** attempt))
        raise RuntimeError(f"WB request failed: {last_error}") from last_error

    async def fetch_products_page(
        self,
        *,
        query: str,
        sort: str,
        page: int,
        dest: str,
        price_min: int | None,
        price_max: int | None,
    ) -> tuple[list[dict[str, Any]], int]:
        params = _build_params(
            query=query, resultset="catalog", sort=sort,
            page=page, dest=dest, price_min=price_min, price_max=price_max,
        )
        data, retries = await self._request_json(params=params)
        return data.get("products") or [], retries

    async def fetch_price_bounds(self, *, query: str, dest: str) -> tuple[int, int]:
        # Сначала пробуем из фильтров
        params = _build_params(query=query, resultset="filters", dest=dest)
        data, _ = await self._request_json(params=params)
        for item in data.get("filters") or []:
            is_price = "price" in str(item.get("name", "")).lower() or str(item.get("id", "")).lower() == "priceu"
            if not is_price:
                continue
            min_v, max_v = item.get("min"), item.get("max")
            if isinstance(min_v, int) and isinstance(max_v, int):
                return min_v, max_v

        # Если фильтры не дали – берём из первой страницы каталога
        products, _ = await self.fetch_products_page(
            query=query, sort="popular", page=1, dest=dest,
            price_min=None, price_max=None,
        )
        prices = _extract_raw_prices(products)
        if prices:
            return min(prices), max(prices)
        raise RuntimeError(
            f"WB не вернул priceU для запроса '{query}'. "
            "Передайте --price-min и --price-max вручную."
        )

    async def fetch_main_menu_tree(self) -> list[dict[str, Any]]:
        async with self._session.get(WB_MENU_URL, timeout=self._timeout) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
            if isinstance(payload, list):
                return payload
            raise RuntimeError("WB menu JSON вернул неожиданный формат.")

    async def resolve_query_from_category_url(self, category_url: str) -> str:
        if manual := parse_search_query_from_url(category_url):
            return manual

        normalized = normalize_url(category_url)
        parsed = urlparse(category_url)
        base = f"{parsed.scheme}://{parsed.netloc}"

        for node in self._iter_menu_nodes(await self.fetch_main_menu_tree()):
            raw_url = node.get("url")
            if not raw_url:
                continue
            candidate = (base + raw_url) if raw_url.startswith("/") else raw_url
            if normalize_url(candidate) != normalized:
                continue
            q = node.get("searchQuery") or node.get("searchquery") or node.get("query") or node.get("name")
            if q:
                return str(q).strip()

        raise RuntimeError("Не удалось определить query по ссылке. Передайте --query вручную.")

    @staticmethod
    def _iter_menu_nodes(nodes: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
        queue = deque(nodes)
        while queue:
            node = queue.popleft()
            yield node
            children = node.get("childs") or node.get("children") or []
            if isinstance(children, list):
                queue.extend(children)