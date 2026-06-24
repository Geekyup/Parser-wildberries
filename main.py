"""
Wildberries parser — CLI entry point.

Usage:
    python main.py https://www.wildberries.ru/catalog/muzhchinam/odezhda/bryuki-i-shorty
    python main.py --query "джинсы" --target-count 500
    python main.py URL --price-min 1000 --price-max 5000

Credentials (any one method works):
    1. cookies.txt  — Netscape cookie export (EditThisCookie / curl)
    2. .env file    — WB_X_WBAAS_TOKEN=... and WB_WBAUID=...
    3. env vars     — export WB_X_WBAAS_TOKEN=... WB_WBAUID=...
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Sequence

import requests

from wb_parser.client import WildberriesClient
from wb_parser.collector import ProductCollector
from wb_parser.config import (
    DEFAULT_CATEGORY_URL,
    DEFAULT_DELAY,
    DEFAULT_DEST,
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_PAGES,
    DEFAULT_MIN_PRICE_SPAN,
    DEFAULT_SORTS,
    DEFAULT_SPLIT_THRESHOLD,
    DEFAULT_TARGET_COUNT,
    DEFAULT_TIMEOUT,
    ApiCredentials,
    CollectorSettings,
)
from wb_parser.credentials import load_cookies_into_env, load_env_file
from wb_parser.exporter import save_excel
from wb_parser.utils import format_elapsed, slugify


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Парсер Wildberries: категория или поисковая выдача → Excel.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("category_url", nargs="?", default=DEFAULT_CATEGORY_URL,
                        help="Ссылка на категорию WB или поисковую выдачу.")
    parser.add_argument("--query", help="Ручной поисковый запрос.")
    parser.add_argument("--output-prefix", help="Имя выходного Excel без расширения.")
    parser.add_argument("--target-count", type=int, default=DEFAULT_TARGET_COUNT)
    parser.add_argument("--dest", default=DEFAULT_DEST)
    parser.add_argument("--sorts", nargs="+", default=list(DEFAULT_SORTS))
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    parser.add_argument("--split-threshold", type=int, default=DEFAULT_SPLIT_THRESHOLD)
    parser.add_argument("--min-price-span", type=int, default=DEFAULT_MIN_PRICE_SPAN)
    parser.add_argument("--price-min", type=int)
    parser.add_argument("--price-max", type=int)
    parser.add_argument("--device-id", help="deviceId вручную.")
    parser.add_argument("--env-file", default=".env", help="Путь до .env файла с cookie.")
    parser.add_argument("--log-level", default="INFO",
                        choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return parser


def _validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    for flag, value in (
        ("--target-count", args.target_count),
        ("--max-pages", args.max_pages),
        ("--timeout", args.timeout),
        ("--split-threshold", args.split_threshold),
        ("--min-price-span", args.min_price_span),
    ):
        if value <= 0:
            parser.error(f"{flag} должен быть больше 0.")

    if args.max_depth < 0:
        parser.error("--max-depth не может быть отрицательным.")
    if args.delay < 0:
        parser.error("--delay не может быть отрицательным.")
    if not args.category_url.strip():
        parser.error("Ссылка на категорию не должна быть пустой.")
    if (args.price_min is None) != (args.price_max is None):
        parser.error("Передайте и --price-min, и --price-max одновременно.")
    if args.price_min is not None and args.price_min > args.price_max:
        parser.error("--price-min не может быть больше --price-max.")


def run(argv: Sequence[str] | None = None) -> tuple[Path, int]:
    started_at = time.perf_counter()

    parser = _build_parser()
    args = parser.parse_args(argv)
    _validate_args(args, parser)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(message)s",
    )

    load_cookies_into_env("cookies.txt")
    load_env_file(args.env_file)

    category_url = args.category_url.strip()
    manual_query = (args.query or "").strip() or None
    output_prefix = (args.output_prefix or "").strip() or None
    sorts = tuple(dict.fromkeys(args.sorts))

    credentials = ApiCredentials.from_env(device_id=args.device_id)
    settings = CollectorSettings(
        target_count=args.target_count,
        dest=args.dest,
        sorts=sorts,
        max_pages=args.max_pages,
        delay=args.delay,
        timeout=args.timeout,
        max_depth=args.max_depth,
        split_threshold=args.split_threshold,
        min_price_span=args.min_price_span,
        price_min=args.price_min,
        price_max=args.price_max,
    )

    with requests.Session() as session:
        client = WildberriesClient(
            session,
            credentials=credentials,
            referer=category_url,
            timeout=settings.timeout,
        )
        query = (manual_query or client.resolve_query_from_category_url(category_url)).strip()
        prefix = output_prefix or slugify(query or category_url)
        output_path = Path(f"{prefix}.xlsx").resolve()

        logging.getLogger(__name__).info("[start] query=%s", query)
        logging.getLogger(__name__).info("[start] url=%s", category_url)

        rows = ProductCollector(client, settings).collect(query=query)

    save_excel(rows, output_path)

    elapsed = time.perf_counter() - started_at
    logging.getLogger(__name__).info("[done] сохранено %s товаров за %s", len(rows), format_elapsed(elapsed))
    logging.getLogger(__name__).info("%s", output_path)
    return output_path, len(rows)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\nОстановлено пользователем.", file=sys.stderr)
        sys.exit(130)
    except ValueError as e:
        print(e, file=sys.stderr)
        sys.exit(2)
