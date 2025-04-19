import pytest_mock

from anti_cf._flaresolverr import check_flaresolverr_api, ensure_flaresolverr_running, start_flaresolverr_docker


def test_check_flaresolverr_api_success(mocker: pytest_mock.MockerFixture) -> None:
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_get = mocker.patch("requests.get", return_value=mock_response)

    assert check_flaresolverr_api() is True
    mock_get.assert_called_once()


def test_check_flaresolverr_api_failure(mocker: pytest_mock.MockerFixture) -> None:
    mocker.patch("requests.get", side_effect=Exception("Connection error"))

    assert check_flaresolverr_api() is False


def test_start_flaresolverr_docker_success(mocker: pytest_mock.MockerFixture) -> None:
    mock_process = mocker.Mock()
    mocker.patch("subprocess.Popen", return_value=mock_process)
    mocker.patch("time.sleep")
    mocker.patch("anti_cf._flaresolverr.check_flaresolverr_api", side_effect=[False, True])

    result = start_flaresolverr_docker()

    assert result == mock_process


def test_start_flaresolverr_docker_failure(mocker: pytest_mock.MockerFixture) -> None:
    mocker.patch("subprocess.Popen", side_effect=Exception("Docker error"))

    result = start_flaresolverr_docker()

    assert result is None


def test_ensure_flaresolverr_running_already_running(mocker: pytest_mock.MockerFixture) -> None:
    mocker.patch("anti_cf._flaresolverr.check_flaresolverr_api", return_value=True)
    mock_start = mocker.patch("anti_cf._flaresolverr.start_flaresolverr_docker")

    result = ensure_flaresolverr_running()

    assert result is None
    mock_start.assert_not_called()


def test_ensure_flaresolverr_running_needs_start(mocker: pytest_mock.MockerFixture) -> None:
    mock_process = mocker.Mock()
    mocker.patch("anti_cf._flaresolverr.check_flaresolverr_api", return_value=False)
    mocker.patch("anti_cf._flaresolverr.start_flaresolverr_docker", return_value=mock_process)

    result = ensure_flaresolverr_running()

    assert result == mock_process
