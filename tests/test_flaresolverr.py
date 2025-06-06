from unittest.mock import MagicMock

import pytest_mock

from anti_cf._flaresolverr import ensure_flaresolverr_running, get_flaresolverr_settings, start_flaresolverr_docker


def test_check_flaresolverr_api_success(mocker: pytest_mock.MockerFixture) -> None:
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_get = mocker.patch("requests.get", return_value=mock_response)

    assert get_flaresolverr_settings() is not None
    mock_get.assert_called_once()


def test_check_flaresolverr_api_failure(mocker: pytest_mock.MockerFixture) -> None:
    mocker.patch("requests.get", side_effect=Exception("Connection error"))

    assert get_flaresolverr_settings() is None


def test_start_flaresolverr_docker_success(mocker: pytest_mock.MockerFixture) -> None:
    mock_process = mocker.Mock()
    mocker.patch("subprocess.Popen", return_value=mock_process)
    mocker.patch("time.sleep")
    mocker.patch("anti_cf._flaresolverr.get_flaresolverr_settings", side_effect=[None, {}])

    result = start_flaresolverr_docker()

    assert result == mock_process


def test_start_flaresolverr_docker_failure(mocker: pytest_mock.MockerFixture, mock_logger: dict[str, MagicMock]) -> None:
    mock_process = mocker.Mock()
    mocker.patch("subprocess.Popen", return_value=mock_process)
    mocker.patch("time.sleep")
    mocker.patch("anti_cf._flaresolverr.get_flaresolverr_settings", return_value=None)

    result = start_flaresolverr_docker()

    assert result == mock_process
    mock_logger["info"].assert_called_with("Starting FlareSolverr docker container...")
    mock_logger["error"].assert_called_with("FlareSolverr container started but API not responding")
    mock_logger["warning"].assert_not_called()
    mock_logger["exception"].assert_not_called()


def test_start_flaresolverr_docker_failure2(mocker: pytest_mock.MockerFixture) -> None:
    mocker.patch("subprocess.Popen", side_effect=Exception("Docker error"))

    result = start_flaresolverr_docker()

    assert result is None


def test_ensure_flaresolverr_running_already_running(mocker: pytest_mock.MockerFixture) -> None:
    mocker.patch("anti_cf._flaresolverr.get_flaresolverr_settings", return_value={})
    mock_start = mocker.patch("anti_cf._flaresolverr.start_flaresolverr_docker")

    result = ensure_flaresolverr_running()

    assert result is None
    mock_start.assert_not_called()


def test_ensure_flaresolverr_running_needs_start(mocker: pytest_mock.MockerFixture) -> None:
    mock_process = mocker.Mock()
    mocker.patch("anti_cf._flaresolverr.get_flaresolverr_settings", return_value=None)
    mocker.patch("anti_cf._flaresolverr.start_flaresolverr_docker", return_value=mock_process)

    result = ensure_flaresolverr_running()

    assert result == mock_process
