from __future__ import annotations

import pickle
import tempfile
from typing import TYPE_CHECKING, ClassVar

import fake_useragent
from logprise import logger
from requests import HTTPError

from ._constants import CACHE_PATH, DEFAULT_TIMEOUT, FLARESOLVERR_PROXY
from ._flaresolverr import ensure_flaresolverr_running, get_flaresolverr_settings

try:
    from requests_cache import CachedSession as Session

    _HAS_CACHE = True
    logger.info("Using CachedSession for persistent session")
except ImportError:
    from requests import Session

    _HAS_CACHE = False

if TYPE_CHECKING:
    from pathlib import Path

    from requests import Response


class PersistentSession(Session):
    _COOKIES_FILE: ClassVar[Path] = CACHE_PATH / "cookies.pkl"
    _USER_AGENT_FILE: ClassVar[Path] = CACHE_PATH / "user_agent.txt"

    def __init__(self) -> None:
        if _HAS_CACHE:
            super().__init__(
                CACHE_PATH / "url_cache.sqlite",
                backend="sqlite",
                cache_control=False,
                expire_after=2 * 3600,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                },
            )
        else:
            super().__init__()

        self._load_cookies()
        self.set_user_agent()
        self._flaresolverr_initialized = False

    def _get_user_agent(self) -> str:
        # Try FlareSolverr first, but don't start it if not running
        flaresolverr_settings = get_flaresolverr_settings()
        if flaresolverr_settings is not None:
            return flaresolverr_settings["userAgent"]

        if self._USER_AGENT_FILE.exists():
            return self._USER_AGENT_FILE.read_text(encoding="utf8").strip()

        return fake_useragent.UserAgent(os="windows", platforms="pc", browsers="chrome").random

    def set_user_agent(self, user_agent: str | None = None) -> None:
        if user_agent is None:
            user_agent = self._get_user_agent()

        self.headers["User-Agent"] = user_agent
        self._USER_AGENT_FILE.write_text(user_agent, encoding="utf8")

    def _load_cookies(self) -> None:
        """Load cookies from file if it exists."""
        if self._COOKIES_FILE.exists():
            try:
                with self._COOKIES_FILE.open("rb") as fp:
                    self.cookies.update(pickle.load(fp))
            except Exception as e:
                logger.error(f"Failed to load cookies from {self._COOKIES_FILE}: {e}")
                self._COOKIES_FILE.unlink()

    def save_cookies(self) -> None:
        """Save current cookies to file."""
        temp_file = Path(tempfile.mktemp(dir=self._COOKIES_FILE.parent))
        temp_file.write_bytes(pickle.dumps(self.cookies, protocol=4))
        temp_file.replace(self._COOKIES_FILE)

    def request(self, *args: object, **kwargs: object) -> Response:
        """Override request method to save cookies after each request."""
        response = super().request(*args, **kwargs)
        self.save_cookies()
        return response

    def _ensure_flaresolverr_initialized(self) -> None:
        """Ensure FlareSolverr is ready when needed."""
        if not self._flaresolverr_initialized:
            ensure_flaresolverr_running()
            self._flaresolverr_initialized = True

    def get(self, url: str | bytes, *, try_with_cloudflare: bool = False, _cloudflare_counter: int = 0, **kwargs: object) -> Response | None:
        if not try_with_cloudflare or "cf_clearance" in self.cookies:
            try:
                resp = super().get(url, **kwargs)
                resp.raise_for_status()
                return resp
            except HTTPError as e:
                if b"just a moment" not in e.response.content.lower():
                    logger.error("No cloudflare trigger in response?")
                    with tempfile.NamedTemporaryFile(delete=False) as f:
                        f.write(e.response.content)
                        logger.error(f"No cloudflare trigger in response? [exception: {e}] [content: {f.name}]")
                    logger.exception(e)
                    return None

                if try_with_cloudflare:
                    logger.warning("Cloudflare cookie expired")
                else:
                    logger.warning("Cloudflare detected, but `try_with_cloudflare` wasn't set to True!")

        self._ensure_flaresolverr_initialized()

        try:
            self._get_url_via_flaresolverr(url)
            return super().get(url, **kwargs)
        except Exception:
            logger.error("FlareSolverr didn't solve it :(")
            raise

    def _get_url_via_flaresolverr(self, url: str) -> dict:
        headers = {"Content-Type": "application/json"}
        data = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": DEFAULT_TIMEOUT * 1_000,
        }
        response = self.post(FLARESOLVERR_PROXY + "v1", headers=headers, json=data, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()

        dta = response.json()
        for cookie in dta["solution"]["cookies"]:
            self.cookies.set(
                name=cookie["name"],
                value=cookie["value"],
                version=cookie.get("version", 0),
                port=cookie.get("port", None),
                domain=cookie.get("domain", ""),
                path=cookie.get("path", "/"),
                secure=cookie.get("secure", False),
                expires=cookie.get("expires", None),
                discard=cookie.get("discard", True),
                comment=cookie.get("comment", None),
                comment_url=cookie.get("comment_url", None),
                rest=cookie.get("rest", {"HttpOnly": None}),
                rfc2109=cookie.get("rfc2109", False),
            )
        self.save_cookies()

        return dta


session = PersistentSession()
