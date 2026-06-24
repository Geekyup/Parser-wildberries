from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

import requests

from .client import WildberriesClient
from .collector import ProductCollector
from .config import ApiCredentials, CollectorSettings
from .credentials import load_cookies_into_env, load_env_file
from .exporter import save_excel
from .utils import format_elapsed, slugify

__all__ = [
    "ApiCredentials",
    "CollectorSettings",
    "ProductCollector",
    "save_excel",
    "run_scraping",
]


class ScrapingCancelled(Exception):
    pass


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
    Запустить сбор товаров WB и сохранить в Excel.
    Возвращает (output_path, count).
    Бросает ScrapingCancelled если should_cancel() вернул True.
    """
    def log(msg: str) -> None:
        logging.getLogger(__name__).info(msg)
        if log_callback:
            log_callback(msg)

    if cookies_file:
        load_cookies_into_env(cookies_file)
    load_env_file(env_file)

    credentials = ApiCredentials.from_env()
    settings = CollectorSettings(
        target_count=target_count,
        max_pages=max_pages,
        delay=delay,
        price_min=price_min,
        price_max=price_max,
    )

    started_at = time.perf_counter()

    with requests.Session() as session:
        client = WildberriesClient(
            session,
            credentials=credentials,
            referer=category_url,
            timeout=settings.timeout,
        )
        query = (manual_query or client.resolve_query_from_category_url(category_url)).strip()
        log(f"Запрос: {query}")
        log(f"Категория: {category_url}")

        # Wrap collector to support cancellation and progress reporting
        collector = ProductCollector(client, settings)
        original_crawl = collector._crawl_segment

        pages_done = [0]

        def crawl_with_hooks(*args, **kwargs):
            if should_cancel and should_cancel():
                raise ScrapingCancelled()
            result = original_crawl(*args, **kwargs)
            pages_done[0] += result.pages
            if progress_callback:
                progress_callback(min(pages_done[0], target_count), target_count)
            return result

        collector._crawl_segment = crawl_with_hooks
        rows = collector.collect(query=query)

    output_path = Path(output_file).resolve()
    save_excel(rows, output_path)

    elapsed = time.perf_counter() - started_at
    log(f"Готово: {len(rows)} товаров за {format_elapsed(elapsed)}")
    log(str(output_path))
    return output_path, len(rows)
