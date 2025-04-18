from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_mock
from requests import HTTPError, Response


@pytest.fixture
def mock_session_get(mocker: pytest_mock.MockerFixture) -> MagicMock:
    """Mock Session.get method."""
    return mocker.patch("requests.Session.get")


@pytest.fixture
def mock_logger(mocker: pytest_mock.MockerFixture) -> dict[str, MagicMock]:
    """Mock logger."""
    return {
        "info": mocker.patch("anti_cf._persistent_session.logger.info"),
        "error": mocker.patch("anti_cf._persistent_session.logger.error"),
        "warning": mocker.patch("anti_cf._persistent_session.logger.warning"),
        "exception": mocker.patch("anti_cf._persistent_session.logger.exception"),
    }


@pytest.fixture
def cloudflare_response() -> MagicMock:
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
def standard_response() -> MagicMock:
    """Create a standard mock response."""
    resp = MagicMock(spec=Response)
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def cloudflare_error() -> HTTPError:
    """Create a cloudflare error response."""
    error_response = MagicMock(spec=Response)
    error_response.content = b"just a moment"
    error = HTTPError("403 Client Error: Forbidden")
    error.response = error_response
    return error


@pytest.fixture(autouse=True)
def generic_files_should_not_exist(tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
    mocker.patch("anti_cf._persistent_session.PersistentSession._COOKIES_FILE", tmp_path / "anti_cf.cookies")
    mocker.patch("anti_cf._persistent_session.PersistentSession._USER_AGENT_FILE", tmp_path / "UA_AGENT.txt")
