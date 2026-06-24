from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

WB_SEARCH_URL = (
    "https://www.wildberries.ru/__internal/u-search/exactmatch/ru/common/v18/search"
)
WB_MENU_URL = (
    "https://static-basket-01.wbbasket.ru/vol0/data/main-menu-ru-ru-v3.json"
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_CATEGORY_URL = (
    "https://www.wildberries.ru/catalog/muzhchinam/odezhda/bryuki-i-shorty"
)
DEFAULT_DEST = "12358062"
DEFAULT_SORTS = ("popular", "newly", "rate")
DEFAULT_TARGET_COUNT = 1000
DEFAULT_TIMEOUT = 20
DEFAULT_DELAY = 0.25
DEFAULT_MAX_PAGES = 4
DEFAULT_MAX_DEPTH = 10
DEFAULT_MIN_PRICE_SPAN = 500
DEFAULT_SPLIT_THRESHOLD = 180

# ---------------------------------------------------------------------------
# Excel export column schema
# ---------------------------------------------------------------------------

EXPORT_SCHEMA: tuple[tuple[str, str], ...] = (
    ("name", "Название"),
    ("brand", "Бренд"),
    ("store_name", "Магазин"),
    ("product_rating", "Рейтинг товара"),
    ("seller_rating", "Рейтинг продавца"),
    ("reviews_count", "Отзывы"),
    ("price_rub", "Цена, руб"),
    ("link", "Ссылка на товар"),
)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ApiCredentials:
    x_wbaas_token: str
    wb_uid: str
    device_id: str

    @classmethod
    def from_env(cls, *, device_id: str | None = None) -> "ApiCredentials":
        x_wbaas_token = os.environ.get("WB_X_WBAAS_TOKEN", "").strip()
        wb_uid = os.environ.get("WB_WBAUID", "").strip()
        resolved_device_id = (
            (device_id or os.environ.get("WB_DEVICE_ID", "")).strip()
            or "device_default"
        )

        missing: list[str] = []
        if not x_wbaas_token:
            missing.append("x_wbaas_token")
        if not wb_uid:
            missing.append("_wbauid")

        if missing:
            raise ValueError(
                "Не заполнены обязательные cookie/параметры: "
                + ", ".join(missing)
                + ". Укажите их в cookies.txt, .env или через параметры."
            )

        return cls(
            x_wbaas_token=x_wbaas_token,
            wb_uid=wb_uid,
            device_id=resolved_device_id,
        )


@dataclass(frozen=True, slots=True)
class CollectorSettings:
    target_count: int = DEFAULT_TARGET_COUNT
    dest: str = DEFAULT_DEST
    sorts: tuple[str, ...] = DEFAULT_SORTS
    max_pages: int = DEFAULT_MAX_PAGES
    delay: float = DEFAULT_DELAY
    timeout: int = DEFAULT_TIMEOUT
    max_depth: int = DEFAULT_MAX_DEPTH
    split_threshold: int = DEFAULT_SPLIT_THRESHOLD
    min_price_span: int = DEFAULT_MIN_PRICE_SPAN
    price_min: int | None = None
    price_max: int | None = None
