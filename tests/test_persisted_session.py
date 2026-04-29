import pickle
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import pytest_mock
from requests import HTTPError

from anti_cf._persistent_session import PersistentSession, session

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _dont_check_flaresolverr_settings(mocker: pytest_mock.MockerFixture) -> None:
    mocker.patch("anti_cf._persistent_session.get_flaresolverr_settings", return_value=None)
    mocker.patch("anti_cf._persistent_session.ensure_flaresolverr_running")


def test_session_initialization() -> None:
    """Test that the exported session is a PersistentSession instance."""
    assert isinstance(session, PersistentSession)


def test_persistent_session_init() -> None:
    """Test PersistentSession initialization."""
    # Create new session instance
    ps = PersistentSession()

    # Verify user agent is set
    assert "User-Agent" in ps.headers

    # Verify behavior, not implementation details
    assert isinstance(ps.headers, Mapping)


def test_get_user_agent_from_file() -> None:
    """Test getting user agent from file."""
    # Setup - create a real user agent file
    test_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    PersistentSession._USER_AGENT_FILE.write_text(test_ua)

    # Test
    ps = PersistentSession()

    # Verify
    assert ps.headers["User-Agent"] == test_ua


def test_get_user_agent_new(mocker: pytest_mock.MockerFixture) -> None:
    """Test getting new user agent when file doesn't exist."""
    # Setup - specify a non-existent file
    fake_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0"

    mock_user_agent = mocker.MagicMock(random=fake_agent)
    mocker.patch("fake_useragent.UserAgent", return_value=mock_user_agent)

    PersistentSession._USER_AGENT_FILE.unlink(missing_ok=True)

    # Test
    ps = PersistentSession()

    # Verify
    assert ps.headers["User-Agent"] == fake_agent


def test_set_user_agent() -> None:
    """Test setting a user agent."""
    # Test
    ps = PersistentSession()
    test_agent = "Custom User Agent 1.0"
    ps.set_user_agent(test_agent)

    # Verify
    assert ps.headers["User-Agent"] == test_agent


def test_load_cookies_exists() -> None:
    """Test loading cookies when file exists."""
    # Setup - create a real cookie file in tmp_path
    cookies = {"domain.com": {"sessionid": "abc123"}}
    PersistentSession._COOKIES_FILE.write_bytes(pickle.dumps(cookies))

    ps = PersistentSession()

    # Verify cookies were loaded
    assert len(ps.cookies) > 0
    assert "sessionid" in ps.cookies.get_dict()["domain.com"]


def test_load_cookies_exception(mock_logger: dict[str, MagicMock]) -> None:
    """Test exception handling when loading cookies."""
    # Setup - create an invalid cookie file
    assert not PersistentSession._COOKIES_FILE.exists()

    PersistentSession._COOKIES_FILE.write_text("This is not a valid pickle file")

    # Test - shouldn't raise an exception
    PersistentSession()

    # Verify logger was called and file was deleted
    assert mock_logger["error"].called
    assert not PersistentSession._COOKIES_FILE.exists()


def test_save_cookies() -> None:
    """Test saving cookies to file."""
    # Setup
    # Test
    ps = PersistentSession()
    ps.cookies.set("test_cookie", "test_value", domain="example.com")
    ps.save_cookies()

    # Verify file was created and contains cookies
    assert PersistentSession._COOKIES_FILE.exists()
    loaded_cookies = pickle.loads(PersistentSession._COOKIES_FILE.read_bytes())
    assert "test_cookie" in loaded_cookies.get_dict("example.com")


def test_request_saves_cookies(mocker: pytest_mock.MockerFixture) -> None:
    """Test that request method saves cookies."""
    # Setup
    ps = PersistentSession()
    mock_save = mocker.patch.object(ps, "save_cookies")
    mocker.patch("requests.Session.request", return_value=mocker.MagicMock())

    # Test
    ps.request("GET", "https://example.com")

    # Verify
    assert mock_save.called


def test_get_method_simple(standard_response: MagicMock, mocker: pytest_mock.MockerFixture) -> None:
    """Test simple GET request without cloudflare."""
    # Setup
    mocker.patch("requests.Session.get", return_value=standard_response)
    mocker.patch("requests.Session.post")

    # Test
    ps = PersistentSession()
    result = ps.get("https://example.com")

    # Verify
    assert result == standard_response


def test_get_method_with_cloudflare_cookie(mocker: pytest_mock.MockerFixture) -> None:
    """Test GET with existing cloudflare cookie."""
    # Setup
    ps = PersistentSession()
    ps.cookies.set("cf_clearance", "value", domain="example.com")
    mock_get = mocker.patch("requests.Session.get", return_value=mocker.MagicMock())

    # Test
    ps.get("https://example.com", try_with_cloudflare=True)

    # Verify normal request was made
    assert mock_get.called


def test_get_method_with_expired_cloudflare_cookie(mocker: pytest_mock.MockerFixture, cloudflare_error: HTTPError, mock_logger: dict[str, MagicMock]) -> None:
    """Test GET with existing cloudflare cookie."""
    # Setup
    ps = PersistentSession()
    ps.cookies.set("cf_clearance", "value", domain="example.com")
    mocker.patch("requests.Session.get", side_effect=[cloudflare_error, None])
    mocker.patch("anti_cf._persistent_session.PersistentSession._get_url_via_flaresolverr")

    # Test
    ps.get("https://example.com", try_with_cloudflare=True)
    mock_logger["warning"].assert_called_with("Cloudflare cookie expired")


def test_get_method_cloudflare_detected(mocker: pytest_mock.MockerFixture, cloudflare_error: HTTPError, standard_response: MagicMock) -> None:
    """Test handling cloudflare protection."""
    # Setup - mock the sequence of responses
    ps = PersistentSession()

    # First get raises cloudflare error
    mocker.patch("requests.Session.get", side_effect=[standard_response, cloudflare_error])

    # Mock flaresolverr response
    mock_post = mocker.patch("requests.Session.post")
    mock_post.return_value = mocker.MagicMock()
    mock_post.return_value.json.return_value = {
        "solution": {
            "cookies": [
                {
                    "name": "cf_clearance",
                    "value": "abc123",
                    "domain": "example.com",
                }
            ]
        }
    }

    # Test
    result = ps.get("https://example.com", try_with_cloudflare=True)

    # Verify
    assert result == standard_response
    assert mock_post.called


def test_get_method_non_cloudflare_error(mocker: pytest_mock.MockerFixture, mock_logger: dict[str, MagicMock]) -> None:
    """Test handling non-cloudflare error."""
    # Setup
    ps = PersistentSession()

    # Create error
    error_response = mocker.MagicMock()
    error_response.content = b"Access denied"

    error = HTTPError("403 Client Error")
    error.response = error_response

    mocker.patch("requests.Session.get", side_effect=error)
    mocker.patch("tempfile.NamedTemporaryFile")
    mocker.patch("anti_cf._persistent_session.PersistentSession._get_url_via_flaresolverr")

    # Test
    assert ps.get("https://example.com") is None
    mock_logger["info"].assert_not_called()
    mock_logger["warning"].assert_any_call("No cloudflare trigger in response?")
    mock_logger["error"].assert_not_called()
    mock_logger["exception"].assert_not_called()


def test_get_method_flaresolverr_exception(mocker: pytest_mock.MockerFixture, cloudflare_error: HTTPError) -> None:
    """Test handling flaresolverr exception."""
    # Setup
    ps = PersistentSession()

    # First get raises cloudflare error
    mocker.patch("requests.Session.get", side_effect=cloudflare_error)

    # FlareSolverr fails
    flare_error = Exception("FlareSolverr error")
    mocker.patch("requests.Session.post", side_effect=flare_error)

    # Test
    with pytest.raises(Exception) as exc_info:
        ps.get("https://example.com", try_with_cloudflare=True)

    # Verify
    assert exc_info.value == flare_error


def test_get_url_direct(mocker: pytest_mock.MockerFixture, cloudflare_response: MagicMock) -> None:
    # Setup
    ps = PersistentSession()
    call_to_flaresolverr = mocker.patch.object(ps, "post", return_value=cloudflare_response)

    # Test
    ps.get("https://example.com")

    # Verify
    call_to_flaresolverr.assert_not_called()

    assert "cf_clearance" not in ps.cookies


def test_cache_read_succeeds_under_concurrent_exclusive_writer(tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
    """
    Regression for ``sqlite3.OperationalError: database is locked``.

    Why: multiple cron-fired scrapers share ``url_cache.sqlite`` from
    different processes. Pre-fix the cache opened in default rollback-journal
    mode -- a writer briefly holding EXCLUSIVE during COMMIT blocked every
    reader, the default 5s busy_timeout expired, and ``__getitem__``'s
    ``SELECT value FROM responses WHERE key=?`` raised OperationalError mid
    request, crashing the scraper.

    With WAL the reader uses the WAL file and never contends with the
    writer's EXCLUSIVE on the main DB. This test reproduces the contention
    via two independent sqlite3 connections in-process (sqlite enforces
    locks at the file level, not per-process) and asserts the cached
    response is returned despite the held EXCLUSIVE.
    """
    pytest.importorskip("requests_cache")
    import sqlite3

    from requests_cache.models import CachedResponse

    cache_dir = tmp_path / "anti_cf"
    cache_dir.mkdir()
    mocker.patch("anti_cf._persistent_session.CACHE_PATH", cache_dir)

    ps = PersistentSession()

    # Seed one cached response that the production read path can find.
    seeded = CachedResponse(status_code=200, headers={}, content=b"hello", url="http://example.invalid/")
    ps.cache.responses["seed"] = seeded

    db_path = cache_dir / "url_cache.sqlite"

    # Hold an EXCLUSIVE on a separate connection — the lock that, without WAL,
    # blocks every other reader for up to busy_timeout.
    blocker = sqlite3.connect(db_path, timeout=0.1)
    try:
        blocker.execute("BEGIN EXCLUSIVE")

        # Production read path: a low connection-level timeout (0.3s) means
        # *if* WAL were off, the read would raise within a third of a second;
        # we keep the test fast and deterministic that way.
        with ps.cache.responses.connection() as con:
            con.execute("PRAGMA busy_timeout=300")
            row = con.execute("SELECT value FROM responses WHERE key='seed'").fetchone()
        assert row is not None, "WAL should let the reader proceed despite the held EXCLUSIVE"
    finally:
        blocker.close()


def test_sqlite_cache_uses_wal_and_busy_timeout(tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
    """Pragma-level smoke check for the ``wal`` + ``busy_timeout`` kwargs."""
    pytest.importorskip("requests_cache")
    import sqlite3

    cache_dir = tmp_path / "anti_cf"
    cache_dir.mkdir()
    mocker.patch("anti_cf._persistent_session.CACHE_PATH", cache_dir)

    ps = PersistentSession()

    # Pragmas applied at the SQLiteDict level — verify on its own connection.
    with ps.cache.responses.connection() as con:
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert con.execute("PRAGMA busy_timeout").fetchone()[0] == 10_000

    # And the WAL mode persists at the file level — re-open from outside.
    db_path = cache_dir / "url_cache.sqlite"
    con = sqlite3.connect(db_path)
    try:
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        con.close()


def _spy_on_connection_execute(ps: PersistentSession, mocker: pytest_mock.MockerFixture) -> list[str]:
    """
    Capture every ``execute(sql, …)`` issued on the cache's sqlite connection.

    ``sqlite3.Connection.execute`` is read-only so we can't reassign it; instead
    wrap the entire connection in a proxy that forwards every other attribute
    via ``__getattr__`` and records SQL strings on the way through.
    """
    from contextlib import contextmanager

    executed: list[str] = []
    original_connection = ps.cache.responses.connection

    class _Proxy:
        def __init__(self, real: object) -> None:
            self._real = real

        def __getattr__(self, name: str) -> object:
            return getattr(self._real, name)

        def execute(self, sql: str, *args: object, **kwargs: object) -> object:
            executed.append(sql)
            return self._real.execute(sql, *args, **kwargs)

    @contextmanager
    def _wrap_connection(*args: object, **kwargs: object) -> "Iterator[_Proxy]":
        with original_connection(*args, **kwargs) as real_con:
            yield _Proxy(real_con)

    mocker.patch.object(ps.cache.responses, "connection", _wrap_connection)
    return executed


class TestPurgeCache:
    """Cover the on-demand and auto-purge cache cleanup paths."""

    def _seed_responses(self, ps: PersistentSession, *, fresh: int = 1, expired: int = 1, old: int = 0) -> None:
        """Pre-populate the cache with a mix of fresh / expired / old entries."""
        import datetime

        from requests_cache.models import CachedResponse

        now = datetime.datetime.now(tz=datetime.timezone.utc)
        for i in range(fresh):
            ps.cache.responses[f"fresh_{i}"] = CachedResponse(
                status_code=200,
                headers={},
                content=b"f" * 1024,
                url=f"http://example/fresh/{i}",
                expires=now + datetime.timedelta(days=30),
                created_at=now,
            )
        for i in range(expired):
            ps.cache.responses[f"expired_{i}"] = CachedResponse(
                status_code=200,
                headers={},
                content=b"e" * 1024,
                url=f"http://example/expired/{i}",
                expires=now - datetime.timedelta(seconds=60),
                created_at=now,
            )
        # ``old`` entries are still fresh by TTL but their created_at is way back —
        # the size-cap path drops them.
        for i in range(old):
            ps.cache.responses[f"old_{i}"] = CachedResponse(
                status_code=200,
                headers={},
                content=b"o" * 1024,
                url=f"http://example/old/{i}",
                expires=now + datetime.timedelta(days=3650),
                created_at=now - datetime.timedelta(days=365),
            )

    def test_drops_expired_entries(self, tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
        mocker.patch("anti_cf._persistent_session.CACHE_PATH", tmp_path)
        # Block auto-purge during construction so the seed data isn't wiped before we test.
        mocker.patch.object(PersistentSession, "_auto_purge_if_due", autospec=True)

        ps = PersistentSession()
        self._seed_responses(ps, fresh=2, expired=3)
        stats = ps.purge_cache(vacuum=False)

        assert stats["rows_before"] == 5
        assert stats["rows_after"] == 2  # only the two fresh ones survive
        assert sorted(ps.cache.responses.keys()) == ["fresh_0", "fresh_1"]

    def test_older_than_evicts_age_capped_entries(self, tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
        """``older_than`` evicts long-TTL entries that would otherwise live forever."""
        import datetime

        mocker.patch("anti_cf._persistent_session.CACHE_PATH", tmp_path)
        mocker.patch.object(PersistentSession, "_auto_purge_if_due", autospec=True)

        ps = PersistentSession()
        self._seed_responses(ps, fresh=1, expired=0, old=2)
        stats = ps.purge_cache(older_than=datetime.timedelta(days=30), vacuum=False)

        assert stats["rows_before"] == 3
        assert stats["rows_after"] == 1  # only the one fresh-and-young entry survives
        assert sorted(ps.cache.responses.keys()) == ["fresh_0"]

    def test_vacuum_runs_when_requested(self, tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
        mocker.patch("anti_cf._persistent_session.CACHE_PATH", tmp_path)
        mocker.patch.object(PersistentSession, "_auto_purge_if_due", autospec=True)

        ps = PersistentSession()
        self._seed_responses(ps, fresh=1, expired=2)

        executed = _spy_on_connection_execute(ps, mocker)

        ps.purge_cache(vacuum=True)
        assert any(s.upper().strip() == "VACUUM" for s in executed)

    def test_vacuum_skipped_when_not_requested(self, tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
        mocker.patch("anti_cf._persistent_session.CACHE_PATH", tmp_path)
        mocker.patch.object(PersistentSession, "_auto_purge_if_due", autospec=True)

        ps = PersistentSession()
        self._seed_responses(ps, fresh=1, expired=1)
        executed = _spy_on_connection_execute(ps, mocker)

        ps.purge_cache(vacuum=False)
        assert not any(s.upper().strip() == "VACUUM" for s in executed)

    def test_marker_file_touched_after_purge(self, tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
        mocker.patch("anti_cf._persistent_session.CACHE_PATH", tmp_path)
        mocker.patch.object(PersistentSession, "_auto_purge_if_due", autospec=True)

        ps = PersistentSession()
        marker = tmp_path / "url_cache.purged"
        assert not marker.exists()
        ps.purge_cache(vacuum=False)
        assert marker.exists()

    def test_purge_cache_raises_without_requests_cache(self, tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
        """When the optional dep is missing, the method explains itself instead of failing weirdly."""
        mocker.patch("anti_cf._persistent_session.CACHE_PATH", tmp_path)
        mocker.patch.object(PersistentSession, "_auto_purge_if_due", autospec=True)
        ps = PersistentSession()
        mocker.patch("anti_cf._persistent_session._HAS_CACHE", False)
        with pytest.raises(RuntimeError, match="requests_cache"):
            ps.purge_cache()


class TestAutoPurge:
    """Cover the construction-time auto-purge gate."""

    def test_runs_purge_when_marker_missing(self, tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
        mocker.patch("anti_cf._persistent_session.CACHE_PATH", tmp_path)
        purge = mocker.patch.object(PersistentSession, "purge_cache", autospec=True)
        PersistentSession()
        purge.assert_called_once()

    def test_skips_purge_when_marker_recent(self, tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
        mocker.patch("anti_cf._persistent_session.CACHE_PATH", tmp_path)
        marker = tmp_path / "url_cache.purged"
        marker.touch()
        purge = mocker.patch.object(PersistentSession, "purge_cache", autospec=True)
        PersistentSession()
        purge.assert_not_called()

    def test_runs_purge_when_marker_older_than_interval(self, tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
        import os
        import time

        mocker.patch("anti_cf._persistent_session.CACHE_PATH", tmp_path)
        marker = tmp_path / "url_cache.purged"
        marker.touch()
        # Backdate to before the interval window.
        old = time.time() - PersistentSession._AUTO_PURGE_INTERVAL_SECONDS - 60
        os.utime(marker, (old, old))

        purge = mocker.patch.object(PersistentSession, "purge_cache", autospec=True)
        PersistentSession()
        purge.assert_called_once()

    def test_swallows_purge_errors(self, tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
        """A failing housekeeping pass must not break the session constructor."""
        mocker.patch("anti_cf._persistent_session.CACHE_PATH", tmp_path)
        mocker.patch.object(PersistentSession, "purge_cache", side_effect=RuntimeError("boom"))
        # Construction must succeed despite the purge raising.
        ps = PersistentSession()
        assert isinstance(ps, PersistentSession)


def test_lazy_flaresolverr_branches(mocker: pytest_mock.MockerFixture) -> None:
    """Test both FlareSolverr branches: settings check and initialization flag."""
    mock_ensure = mocker.patch("anti_cf._persistent_session.ensure_flaresolverr_running")

    # Branch 1: FlareSolverr running during init (settings not None)
    mocker.patch("anti_cf._persistent_session.get_flaresolverr_settings", return_value={"userAgent": "FlareSolverr/1.0"})
    ps = PersistentSession()
    assert ps.headers["User-Agent"] == "FlareSolverr/1.0"

    # Branch 2: Initialization flag check (not initialized -> initialize)
    ps._flaresolverr_initialized = False
    ps._ensure_flaresolverr_initialized()
    assert mock_ensure.called
    assert ps._flaresolverr_initialized

    # Branch 3: initialized
    mock_ensure.reset_mock()
    ps._ensure_flaresolverr_initialized()
    assert not mock_ensure.called
