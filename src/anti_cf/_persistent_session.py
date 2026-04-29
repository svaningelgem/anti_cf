from __future__ import annotations

import contextlib
import pickle
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
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
    from datetime import timedelta

    from requests import Response


class PersistentSession(Session):
    _COOKIES_FILE: ClassVar[Path] = CACHE_PATH / "cookies.pkl"
    _USER_AGENT_FILE: ClassVar[Path] = CACHE_PATH / "user_agent.txt"

    # Default for the auto-purge cadence on session construction. Long enough
    # that startup cost is amortised across many sessions, short enough that
    # disk usage doesn't drift unboundedly between runs.
    _AUTO_PURGE_INTERVAL_SECONDS: ClassVar[int] = 7 * 24 * 3600  # 7 days

    @property
    def _purge_marker(self) -> Path:
        # Resolved at access time so tests that patch ``CACHE_PATH`` (or any
        # caller redirecting the cache directory mid-run) see the right path.
        return CACHE_PATH / "url_cache.purged"

    def __init__(self) -> None:
        if _HAS_CACHE:
            # WAL + busy_timeout so concurrent scrapers sharing this cache don't
            # raise sqlite3.OperationalError("database is locked"). Without WAL,
            # any writer blocks every other reader/writer; with the default
            # 5s busy_timeout, simultaneous cron-fired scrapers race and one
            # loses. WAL lets readers and one writer proceed in parallel, and
            # 10s gives writers enough headroom for the contended startup.
            super().__init__(
                CACHE_PATH / "url_cache.sqlite",
                backend="sqlite",
                cache_control=False,
                expire_after=2 * 3600,
                wal=True,
                busy_timeout=10_000,
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

        # One-shot best-effort purge if the cache hasn't been swept in a while.
        # Failures are swallowed — this is housekeeping, not a hard requirement.
        if _HAS_CACHE:
            with contextlib.suppress(Exception):
                self._auto_purge_if_due()

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
                    logger.warning("No cloudflare trigger in response?")
                    with tempfile.NamedTemporaryFile(delete=False) as f:
                        f.write(e.response.content)
                        logger.warning(f"No cloudflare trigger in response? [exception: {e}] [content: {f.name}]")
                    # logger.exception(e)
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
            logger.error(f"FlareSolverr didn't solve it :( [url: {url}]")
            raise

    def purge_cache(self, *, older_than: timedelta | None = None, vacuum: bool = True) -> dict[str, int]:
        """
        Reclaim disk space from the persistent SQLite cache.

        Drops every expired response, optionally drops every response whose
        ``created_at`` is older than ``older_than`` regardless of its TTL,
        then ``VACUUM``s the file so the freed pages become free disk.

        ``older_than`` is the size-cap lever: long-TTL entries (10-year image
        bodies and the like) never expire on their own, so without an age
        cap they sit forever. Pass ``timedelta(days=N)`` to evict anything
        older than that.

        Set ``vacuum=False`` to skip the ``VACUUM`` (it rewrites the whole
        file and can take a while on a multi-gigabyte cache; sometimes you
        just want the rows gone and don't care about the on-disk size yet).

        Returns a dict ``{"rows_before", "rows_after", "bytes_before",
        "bytes_after"}`` so callers can log or assert on the savings.
        Raises if the session was constructed without ``requests_cache``
        installed — there is no cache to purge.
        """
        if not _HAS_CACHE:
            raise RuntimeError("purge_cache requires requests_cache to be installed")

        cache_path = CACHE_PATH / "url_cache.sqlite"

        def _file_size() -> int:
            try:
                return cache_path.stat().st_size
            except OSError:
                return 0

        def _row_count() -> int:
            with self.cache.responses.connection() as con:
                return con.execute(f"SELECT COUNT(*) FROM {self.cache.responses.table_name}").fetchone()[0]

        rows_before = _row_count()
        bytes_before = _file_size()

        # Step 1: drop expired entries (TTL says they're past their use).
        # ``vacuum=False`` so the inner cleanup doesn't VACUUM behind our back —
        # we want exactly one VACUUM at the end (or none, if the caller asked).
        self.cache.delete(expired=True, vacuum=False)

        # Step 2: optional age cap — drop anything older than ``older_than`` by created_at.
        if older_than is not None:
            cutoff = datetime.now(timezone.utc) - older_than
            stale_keys = [key for key, resp in self.cache.responses.items() if getattr(resp, "created_at", None) is not None and resp.created_at < cutoff]
            if stale_keys:
                self.cache.delete(*stale_keys, vacuum=False)

        # Step 3: reclaim disk space.
        if vacuum:
            with self.cache.responses.connection() as con:
                con.execute("VACUUM")

        rows_after = _row_count()
        bytes_after = _file_size()

        self._purge_marker.parent.mkdir(parents=True, exist_ok=True)
        self._purge_marker.touch()

        logger.info(
            "Cache purge: rows %d->%d (-%d), size %d->%d bytes (-%d)",
            rows_before,
            rows_after,
            rows_before - rows_after,
            bytes_before,
            bytes_after,
            bytes_before - bytes_after,
        )
        return {
            "rows_before": rows_before,
            "rows_after": rows_after,
            "bytes_before": bytes_before,
            "bytes_after": bytes_after,
        }

    def _auto_purge_if_due(self) -> None:
        """Run :meth:`purge_cache` if the marker file is older than the auto-purge interval."""
        try:
            last_run = self._purge_marker.stat().st_mtime
        except FileNotFoundError:
            last_run = 0
        if (time.time() - last_run) >= self._AUTO_PURGE_INTERVAL_SECONDS:
            self.purge_cache()

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
