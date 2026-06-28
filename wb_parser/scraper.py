from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Callable

import aiohttp

from wb_parser.client import WildberriesClient
from wb_parser.collector import ProductCollector, SegmentStats
from wb_parser.config import ApiCredentials, CollectorSettings
from wb_parser.credentials import load_cookies_into_env, load_env_file
from wb_parser.exporter import save_excel
from wb_parser.utils import format_elapsed


class ScrapingCancelled(Exception):
    """Пользователь нажал «Стоп» во время парсинга."""


class _HookedCollector(ProductCollector):
    """ProductCollector с поддержкой отмены и колбэков прогресса."""

    def __init__(
        self,
        *args,
        should_cancel: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
        target_count: int = 0,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._should_cancel = should_cancel
        self._progress_callback = progress_callback
        self._target_count = target_count
        self._pages_done = 0

    async def _crawl_segment(self, **kwargs) -> SegmentStats:
        if self._should_cancel and self._should_cancel():
            raise ScrapingCancelled()
        result = await super()._crawl_segment(**kwargs)
        self._pages_done += result.pages
        if self._progress_callback:
            self._progress_callback(min(self._pages_done, self._target_count), self._target_count)
        return result


async def _run_async(
    *,
    category_url: str,
    output_file: str,
    target_count: int,
    max_pages: int,
    delay: float,
    price_min: int | None,
    price_max: int | None,
    manual_query: str | None,
    log_callback: Callable[[str], None] | None,
    progress_callback: Callable[[int, int], None] | None,
    should_cancel: Callable[[], bool] | None,
) -> tuple[Path, int]:
    """Внутренняя async-реализация парсинга."""
    logger = logging.getLogger(__name__)

    def log(msg: str) -> None:
        logger.info(msg)
        if log_callback:
            log_callback(msg)

    credentials = ApiCredentials.from_env()
    settings = CollectorSettings(
        target_count=target_count,
        max_pages=max_pages,
        delay=delay,
        price_min=price_min,
        price_max=price_max,
    )

    started_at = time.perf_counter()

    # rate_limit=1.0 — минимум 1 секунда между запросами (с jitter ±50%)
    # Итого реальный интервал: 0.5–1.5 сек, что имитирует живого пользователя
    connector = aiohttp.TCPConnector(limit=1)  # один коннект за раз — без параллельных запросов
    async with aiohttp.ClientSession(connector=connector) as session:
        client = WildberriesClient(
            session,
            credentials=credentials,
            referer=category_url,
            timeout=settings.timeout,
            rate_limit=1.0,
        )
        query = (manual_query or await client.resolve_query_from_category_url(category_url)).strip()
        log(f"Запрос: {query}")
        log(f"Категория: {category_url}")

        collector = _HookedCollector(
            client, settings,
            should_cancel=should_cancel,
            progress_callback=progress_callback,
            target_count=target_count,
        )
        rows = await collector.collect(query=query)

    output_path = Path(output_file).resolve()
    save_excel(rows, output_path)

    elapsed = time.perf_counter() - started_at
    log(f"Готово: {len(rows)} товаров за {format_elapsed(elapsed)}")
    log(str(output_path))
    return output_path, len(rows)


def run_scraping(
    *,
    category_url: str,
    output_file: str,
    target_count: int = 1000,
    max_pages: int = 4,
    delay: float = 0.25,
    price_min: int | None = None,
    price_max: int | None = None,
    manual_query: str | None = None,
    cookies_file: str | None = None,
    env_file: str = ".env",
    log_callback: Callable[[str], None] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[Path, int]:
    """
    Публичный API — синхронная обёртка над async-реализацией.
    GUI и CLI вызывают именно эту функцию, не зная про asyncio.

    Возвращает (путь_к_файлу, кол-во_товаров).
    Бросает ScrapingCancelled если should_cancel() вернул True.
    """
    if cookies_file:
        load_cookies_into_env(cookies_file)
    load_env_file(env_file)

    return asyncio.run(_run_async(
        category_url=category_url,
        output_file=output_file,
        target_count=target_count,
        max_pages=max_pages,
        delay=delay,
        price_min=price_min,
        price_max=price_max,
        manual_query=manual_query,
        log_callback=log_callback,
        progress_callback=progress_callback,
        should_cancel=should_cancel,
    ))