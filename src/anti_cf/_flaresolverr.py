from __future__ import annotations

import subprocess
import time

import requests
from logprise import logger

from ._constants import FLARESOLVERR_PROXY


def check_flaresolverr_api() -> bool:
    """Check if FlareSolverr API is reachable."""
    try:
        resp = requests.get(FLARESOLVERR_PROXY + "v1", timeout=2)
        return resp.status_code == 200
    except:  # noqa: E722
        return False


def start_flaresolverr_docker() -> subprocess.Popen | None:
    """Start the FlareSolverr docker container."""
    try:
        logger.info("Starting FlareSolverr docker container...")
        process = subprocess.Popen(
            ["docker", "run", "--rm", "-p", "8191:8191", "ghcr.io/svaningelgem/flaresolverr:latest"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for container to be ready
        for _ in range(10):  # Try for 10 seconds
            time.sleep(1)
            if check_flaresolverr_api():
                logger.info("FlareSolverr is ready")
                return process

        logger.error("FlareSolverr container started but API not responding")
        return process
    except Exception as e:
        logger.error(f"Failed to start FlareSolverr docker: {e}")
        return None


def ensure_flaresolverr_running() -> subprocess.Popen | None:
    """Ensure FlareSolverr is running, start if needed."""
    if check_flaresolverr_api():
        logger.info("FlareSolverr API is already running")
        return None

    return start_flaresolverr_docker()
