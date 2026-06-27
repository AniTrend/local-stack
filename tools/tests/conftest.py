"""Shared fixtures for tools tests."""
from __future__ import annotations

import pytest


@pytest.fixture
def sample_service_dict():
    """Return a minimal service dict with image, env_file, labels, and volumes."""
    return {
        "image": "nginx:alpine",
        "env_file": "./cwd/.env",
        "labels": [
            'traefik.rule=Host(`${HOST}`)',
            'traefik.port=${PORT:-8080}',
        ],
        "volumes": [
            "app-data:/data",
            "./cwd/config:/etc/app:ro",
        ],
    }
