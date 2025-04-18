from __future__ import annotations

from pathlib import Path
from typing import Final

CACHE_PATH = Path.home() / ".cache/anti_cf"
FLARESOLVERR_PROXY: Final[str] = "http://localhost:8191/"
CACHE_PATH.mkdir(exist_ok=True, parents=True)
DEFAULT_TIMEOUT: int = 600
