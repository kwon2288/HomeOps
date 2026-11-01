from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import Runtime, Settings
from app.main import create_app


@pytest.fixture
def runtime(tmp_path):
    return Runtime(
        admin_user="admin", admin_password="pw", secret_key="test-secret", cookie_secure=False,
        db_path=tmp_path / "homeops.db", backup_dir=tmp_path / "backups", backup_keep=2,
    )


@pytest.fixture
def web_runtime(tmp_path):
    """환경 변수 계정 없이 웹에서 계정을 만드는 경우."""
    return Runtime(
        secret_key="test-secret", cookie_secure=None,
        db_path=tmp_path / "homeops.db", backup_dir=tmp_path / "backups", backup_keep=2,
    )


def make_client(settings: Settings, runtime: Runtime, login: bool = True) -> TestClient:
    auth._fails.clear()
    client = TestClient(create_app(settings, runtime))
    if login:
        r = client.post("/api/auth/login", json={"username": "admin", "password": "pw"})
        assert r.status_code == 200
    return client


@pytest.fixture
def client(runtime):
    return make_client(Settings(), runtime)
