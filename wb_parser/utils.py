from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    clean_path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{clean_path}".lower()


def slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"[^a-zа-я0-9]+", "_", text, flags=re.IGNORECASE)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "wb_export"


def parse_search_query_from_url(url: str) -> str | None:
    query_params = parse_qs(urlparse(url).query)
    for key in ("search", "query", "text"):
        values = query_params.get(key)
        if values and values[0].strip():
            return values[0].strip()
    return None


def format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02}:{minutes:02}:{secs:02}"
    return f"{minutes:02}:{secs:02}"
