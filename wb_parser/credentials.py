from __future__ import annotations

import os
from pathlib import Path


def parse_cookies_txt(cookies_path: str | Path = "cookies.txt") -> dict[str, str]:
    """Parse Netscape HTTP Cookie File (curl / EditThisCookie export)."""
    path = Path(cookies_path)
    if not path.exists():
        return {}
    cookies: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            cookies[parts[5]] = parts[6]
    return cookies


def load_env_file(env_path: str | Path = ".env") -> None:
    """Load key=value pairs from a .env file into os.environ (does not overwrite)."""
    path = Path(env_path)
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def load_cookies_into_env(cookies_path: str | Path = "cookies.txt") -> None:
    """Map known WB cookie names to env vars (does not overwrite existing values)."""
    cookie_map = {
        "x_wbaas_token": "WB_X_WBAAS_TOKEN",
        "X_WBAAS_TOKEN": "WB_X_WBAAS_TOKEN",
        "_wbauid": "WB_WBAUID",
        "WBAUID": "WB_WBAUID",
    }
    cookies = parse_cookies_txt(cookies_path)
    for cookie_name, env_name in cookie_map.items():
        if cookie_name in cookies:
            os.environ.setdefault(env_name, cookies[cookie_name])
