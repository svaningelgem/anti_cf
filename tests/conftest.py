from pathlib import Path
from unittest.mock import MagicMock

import pytest
from requests import Response

import anti_cf._persistent_session


@pytest.fixture
def mock_session_get(mocker):
    """Mock Session.get method."""
    return mocker.patch("requests.Session.get")


@pytest.fixture
def mock_session_post(mocker):
    """Mock Session.post method."""
    return mocker.patch("requests.Session.post")


@pytest.fixture
def mock_logger(mocker) -> dict[str, MagicMock]:
    """Mock logger."""
    return {
        "info": mocker.patch("anti_cf._persistent_session.logger.info"),
        "error": mocker.patch("anti_cf._persistent_session.logger.error"),
        "warning": mocker.patch("anti_cf._persistent_session.logger.warning"),
        "exception": mocker.patch("anti_cf._persistent_session.logger.exception"),
    }


@pytest.fixture
def mock_user_agent(mocker):
    """Mock fake_useragent."""
    mock_ua = MagicMock()
    mock_ua.random = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0"
    return mocker.patch("fake_useragent.UserAgent", return_value=mock_ua)


@pytest.fixture
def cloudflare_response():
    """Create a mock response from flaresolverr."""
    resp = MagicMock(spec=Response)
    resp.json.return_value = {
        "solution": {
            "cookies": [
                {
                    "name": "cf_clearance",
                    "value": "abc123",
                    "domain": "example.com",
                    "path": "/",
                }
            ]
        }
    }
    return resp


@pytest.fixture
def standard_response():
    """Create a standard mock response."""
    resp = MagicMock(spec=Response)
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def cloudflare_error():
    """Create a cloudflare error response."""
    from requests import HTTPError

    error_response = MagicMock(spec=Response)
    error_response.content = b"just a moment"
    error = HTTPError("403 Client Error: Forbidden")
    error.response = error_response
    return error


@pytest.fixture(autouse=True)
def reset_cookies(tmp_path: Path, monkeypatch) -> None:
    """Reset cookies."""
    anti_cf._persistent_session.PersistentSession._COOKIES_FILE = tmp_path / "anti_cf.cookies"
