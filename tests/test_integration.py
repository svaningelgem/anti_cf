from unittest.mock import MagicMock

import pytest
import pytest_mock
from requests import HTTPError

from anti_cf import session
from anti_cf._constants import FLARESOLVERR_PROXY
from anti_cf._persistent_session import PersistentSession


class TestIntegration:
    def test_package_exports_session(self) -> None:
        """Test that the package properly exports session."""
        import anti_cf

        assert hasattr(anti_cf, "session")
        from anti_cf._persistent_session import PersistentSession

        assert isinstance(anti_cf.session, PersistentSession)

    def test_complete_workflow(
        self, mocker: pytest_mock.MockerFixture, cloudflare_error: HTTPError, standard_response: MagicMock, cloudflare_response: MagicMock
    ) -> None:
        """Test the complete workflow of handling a cloudflare-protected site."""
        # Setup sequence of responses:
        # 1. First request fails with cloudflare protection
        # 2. FlareSolverr request succeeds
        # 3. Second request succeeds with cookies

        # Mock Session.get to return our sequence
        mocker.patch("requests.Session.get", side_effect=[standard_response, cloudflare_error])

        # Mock Session.post for FlareSolverr
        mock_post = mocker.patch("requests.Session.post", return_value=cloudflare_response)

        # The actual test
        response = session.get("https://example.com", try_with_cloudflare=True)

        # Verify
        assert response == standard_response

        # Check FlareSolverr was called with correct parameters
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert FLARESOLVERR_PROXY + "v1" in args
        # Verify URL was passed to the proxy
        assert "example.com" in str(kwargs)

    def test_session_reuses_cf_cookie(self, mocker: pytest_mock.MockerFixture, standard_response: MagicMock) -> None:
        """Test that the session reuses cloudflare cookies if they exist."""
        # Setup - add a cloudflare cookie
        session.cookies.set("cf_clearance", "test_value", domain="example.com")
        mock_get = mocker.patch("requests.Session.get", return_value=standard_response)

        # Test
        response = session.get("https://example.com", try_with_cloudflare=True)

        # Verify
        assert response == standard_response
        # Only a single GET request should be made, no FlareSolverr
        mock_get.assert_called_once()

        # Clean up - remove test cookie
        session.cookies.clear()


@pytest.mark.parametrize("try_with_cloudflare", [True, False])
def test_error_handling_based_on_flag(
    mocker: pytest_mock.MockerFixture, cloudflare_error: HTTPError, mock_logger: dict[str, MagicMock], try_with_cloudflare: bool
) -> None:
    """Test error handling behavior with different try_with_cloudflare flags."""
    # Setup
    mocker.patch("requests.Session.get", side_effect=cloudflare_error)
    mock_flaresolverr = mocker.patch("anti_cf._persistent_session.PersistentSession._get_url_via_flaresolverr")

    # Test
    try:
        ps = PersistentSession()
        ps.get("https://example.com", try_with_cloudflare=try_with_cloudflare)
    except:  # noqa: E722
        pass

    assert mock_flaresolverr.called

    # Verify behavior based on flag
    if try_with_cloudflare:
        assert "FlareSolverr didn't solve it" in mock_logger["error"].call_args[0][0]
    else:
        assert mock_logger["warning"].call_args[0][0] == "Cloudflare detected, but `try_with_cloudflare` wasn't set to True!"
