from __future__ import annotations

import time
from collections import deque
from datetime import UTC, datetime
from typing import Any, Iterator
from urllib.parse import urlparse

import requests

from .config import ApiCredentials, WB_MENU_URL, WB_SEARCH_URL
from .utils import normalize_url, parse_search_query_from_url


def _make_query_id(wb_uid: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"qid{wb_uid}{timestamp}"


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


class WildberriesClient:
    def __init__(
        self,
        session: requests.Session,
        *,
        credentials: ApiCredentials,
        referer: str,
        timeout: int,
    ) -> None:
        self._session = session
        self._credentials = credentials
        self._timeout = timeout
        self._base_headers = {
            "accept": "*/*",
            "accept-language": "ru,en;q=0.9",
            "deviceid": credentials.device_id,
            "referer": referer,
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/146.0.0.0 Safari/537.36"
            ),
            "x-requested-with": "XMLHttpRequest",
            "x-spa-version": "14.3.2",
            "x-userid": "0",
        }
        self._cookies = {
            "x_wbaas_token": credentials.x_wbaas_token,
            "_wbauid": credentials.wb_uid,
        }

    def _request_json(
        self,
        *,
        params: dict[str, str],
        retries: int = 3,
    ) -> tuple[dict[str, Any], int]:
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                headers = dict(self._base_headers)
                headers["x-queryid"] = _make_query_id(self._credentials.wb_uid)
                response = self._session.get(
                    WB_SEARCH_URL,
                    params=params,
                    headers=headers,
                    cookies=self._cookies,
                    timeout=self._timeout,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise RuntimeError("WB search API вернул неожиданный формат JSON.")
                return payload, attempt - 1
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < retries:
                    time.sleep(float(attempt))
        raise RuntimeError(f"WB request failed: {last_error}") from last_error

    def fetch_products_page(
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
            query=query,
            resultset="catalog",
            sort=sort,
            page=page,
            dest=dest,
            price_min=price_min,
            price_max=price_max,
        )
        data, retry_errors = self._request_json(params=params)
        return data.get("products") or [], retry_errors

    def fetch_price_bounds(self, *, query: str, dest: str) -> tuple[int, int]:
        params = _build_params(query=query, resultset="filters", dest=dest)
        data, _ = self._request_json(params=params)

        for item in data.get("filters") or []:
            if "price" not in str(item.get("name", "")).lower() and str(item.get("id", "")).lower() != "priceu":
                continue
            min_v, max_v = item.get("min"), item.get("max")
            if isinstance(min_v, int) and isinstance(max_v, int):
                return min_v, max_v

        products, _ = self.fetch_products_page(
            query=query, sort="popular", page=1, dest=dest,
            price_min=None, price_max=None,
        )
        raw_prices: list[int] = []
        for p in products:
            for size in p.get("sizes") or []:
                pp = (size.get("price") or {}).get("product")
                if isinstance(pp, (int, float)):
                    raw_prices.append(int(pp))
            for field in ("salePriceU", "priceU"):
                raw = p.get(field)
                if isinstance(raw, (int, float)):
                    raw_prices.append(int(raw))

        if raw_prices:
            return min(raw_prices), max(raw_prices)
        raise RuntimeError(
            "WB не вернул priceU. Передайте --price-min и --price-max вручную."
        )

    def fetch_main_menu_tree(self) -> list[dict[str, Any]]:
        response = self._session.get(WB_MENU_URL, timeout=self._timeout)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            return payload
        raise RuntimeError("WB menu JSON вернул неожиданный формат.")

    def resolve_query_from_category_url(self, category_url: str) -> str:
        manual = parse_search_query_from_url(category_url)
        if manual:
            return manual

        normalized = normalize_url(category_url)
        parsed = urlparse(category_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        menu_tree = self.fetch_main_menu_tree()

        for node in self._iter_menu_nodes(menu_tree):
            raw_url = node.get("url")
            if not raw_url:
                continue
            candidate = (base + raw_url) if raw_url.startswith("/") else raw_url
            if normalize_url(candidate) != normalized:
                continue
            q = (
                node.get("searchQuery")
                or node.get("searchquery")
                or node.get("query")
                or node.get("name")
            )
            if q:
                return str(q).strip()

        raise RuntimeError(
            "Не удалось определить query по ссылке. Передайте --query вручную."
        )

    @staticmethod
    def _iter_menu_nodes(nodes: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
        queue = deque(nodes)
        while queue:
            node = queue.popleft()
            yield node
            children = node.get("childs") or node.get("children") or []
            if isinstance(children, list):
                queue.extend(children)
