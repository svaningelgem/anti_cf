import pickle
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_mock
from requests import HTTPError

from anti_cf._persistent_session import PersistentSession, session


def test_session_initialization() -> None:
    """Test that the exported session is a PersistentSession instance."""
    assert isinstance(session, PersistentSession)


def test_persistent_session_init(tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
    """Test PersistentSession initialization."""
    # Setup - create directories for session files
    cookies_file = tmp_path / "cookies.pkl"
    ua_file = tmp_path / "user_agent.txt"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    # Patch class variables to use temp files
    mocker.patch.object(PersistentSession, "_COOKIES_FILE", cookies_file)
    mocker.patch.object(PersistentSession, "_USER_AGENT_FILE", ua_file)

    # Create new session instance
    ps = PersistentSession()

    # Verify user agent is set
    assert "User-Agent" in ps.headers

    # Verify behavior, not implementation details
    assert isinstance(ps.headers, Mapping)


def test_get_user_agent_from_file(tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
    """Test getting user agent from file."""
    # Setup - create a real user agent file
    ua_file = tmp_path / "user_agent.txt"
    test_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    ua_file.write_text(test_ua)

    # Patch the _USER_AGENT_FILE class var to use our temp file
    mocker.patch.object(PersistentSession, "_USER_AGENT_FILE", ua_file)

    # Test
    ps = PersistentSession()
    user_agent = ps._get_user_agent()

    # Verify
    assert user_agent == test_ua


def test_get_user_agent_new(tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
    """Test getting new user agent when file doesn't exist."""
    # Setup - specify a non-existent file
    ua_file = tmp_path / "non_existent_user_agent.txt"
    fake_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0"
    ua_file.write_text(fake_agent)

    # Patch the _USER_AGENT_FILE class var to use our temp file
    mocker.patch.object(PersistentSession, "_USER_AGENT_FILE", ua_file)

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


def test_load_cookies_exists(tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
    """Test loading cookies when file exists."""
    # Setup - create a real cookie file in tmp_path
    cookies = {"domain.com": {"sessionid": "abc123"}}
    cookie_file = tmp_path / "cookies.pkl"
    cookie_file.write_bytes(pickle.dumps(cookies))

    # Patch the _COOKIES_FILE class var to use our temp file
    mocker.patch.object(PersistentSession, "_COOKIES_FILE", cookie_file)

    ps = PersistentSession()

    # Verify cookies were loaded
    assert len(ps.cookies) > 0
    assert "sessionid" in ps.cookies.get_dict()["domain.com"]


def test_load_cookies_exception(tmp_path: Path, mock_logger: dict[str, MagicMock], mocker: pytest_mock.MockerFixture) -> None:
    """Test exception handling when loading cookies."""
    # Setup - create an invalid cookie file
    cookie_file = tmp_path / "cookies.pkl"
    cookie_file.write_text("This is not a valid pickle file")

    # Patch the _COOKIES_FILE class var to use our temp file
    mocker.patch.object(PersistentSession, "_COOKIES_FILE", cookie_file)

    # Test - shouldn't raise an exception
    PersistentSession()

    # Verify logger was called and file was deleted
    assert mock_logger["error"].called
    assert not cookie_file.exists()


def test_save_cookies(tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
    """Test saving cookies to file."""
    # Setup
    cookie_file = tmp_path / "cookies.pkl"

    # Patch the _COOKIES_FILE class var to use our temp file
    mocker.patch.object(PersistentSession, "_COOKIES_FILE", cookie_file)

    # Test
    ps = PersistentSession()
    ps.cookies.set("test_cookie", "test_value", domain="example.com")
    ps.save_cookies()

    # Verify file was created and contains cookies
    assert cookie_file.exists()
    loaded_cookies = pickle.loads(cookie_file.read_bytes())
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


def test_get_method_simple(mock_session_get: MagicMock, standard_response: MagicMock, mocker: pytest_mock.MockerFixture) -> None:
    """Test simple GET request without cloudflare."""
    # Setup
    mock_session_get.return_value = standard_response
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


def test_get_method_cloudflare_detected(mocker: pytest_mock.MockerFixture, cloudflare_error: HTTPError, standard_response: MagicMock) -> None:
    """Test handling cloudflare protection."""
    # Setup - mock the sequence of responses
    ps = PersistentSession()

    # First get raises cloudflare error
    mocker.patch("requests.Session.get", side_effect=[cloudflare_error, standard_response])

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


def test_get_method_non_cloudflare_error(mocker: pytest_mock.MockerFixture) -> None:
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
    with pytest.raises(HTTPError, match="403 Client Error"):
        ps.get("https://example.com")


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


def test_get_url_via_flaresolverr(mocker: pytest_mock.MockerFixture, cloudflare_response: MagicMock) -> None:
    """Test FlareSolverr integration."""
    # Setup
    ps = PersistentSession()
    call_to_flaresolverr = mocker.patch.object(ps, "post", return_value=cloudflare_response)
    mocker.patch("requests.Session.get")

    # Test
    ps.get("https://example.com")

    # Verify
    call_to_flaresolverr.assert_called_once()

    # Verify a cookie was set
    cookie_found = False
    for name, _value in ps.cookies.items():
        if name == "cf_clearance":
            cookie_found = True
            break

    assert cookie_found
