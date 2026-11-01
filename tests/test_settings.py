import json

import httpx
import respx

from app.config import Settings
from app.store import MASK

from .conftest import conn, make_client


def test_first_run_setup(web_runtime):
    c = make_client(Settings(), web_runtime, login=False)
    assert c.get("/api/auth/status").json()["needs_setup"] is True
    assert c.post("/api/auth/login", json={"username": "admin", "password": "x"}).status_code == 409
    assert c.post("/api/auth/setup", json={"username": "min", "password": "short"}).status_code == 422
    assert c.post("/api/auth/setup", json={"username": "min", "password": "longenough1"}).status_code == 200
    assert c.get("/api/auth/me").json()["user"] == "min"
    assert c.post("/api/auth/setup", json={"username": "x", "password": "longenough1"}).status_code == 409
    c.post("/api/auth/logout")
    assert c.post("/api/auth/login", json={"username": "min", "password": "wrong-pass"}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "min", "password": "longenough1"}).status_code == 200
    assert c.post("/api/auth/password", json={"current": "nope", "new": "newpassword1"}).status_code == 400
    assert c.post("/api/auth/password", json={"current": "longenough1", "new": "newpassword1"}).status_code == 200
    c.post("/api/auth/logout")
    assert c.post("/api/auth/login", json={"username": "min", "password": "newpassword1"}).status_code == 200


def test_connection_crud_and_secrets(client):
    body = {"type": "proxmox", "name": "집 Proxmox",
            "config": {"url": "https://pve.test:8006/", "token_id": "a@pve!b", "token_secret": "very-secret-value"}}
    r = client.post("/api/connections", json=body)
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["id"] == "proxmox" and created["config"]["token_secret"] == MASK
    assert created["config"]["url"] == "https://pve.test:8006"  # 끝의 / 정리
    assert created["config"]["backup_storage"] == "local"       # 기본값

    # 같은 종류 여러 개 가능 (id 자동)
    second = client.post("/api/connections", json={**body, "name": "두 번째"}).json()
    assert second["id"] == "proxmox-2"

    # 비밀값을 MASK 그대로 보내면 유지
    r = client.put("/api/connections/proxmox", json={"name": "Proxmox", "config": {**created["config"], "backup_storage": "nas"}})
    assert r.status_code == 200
    ctx = client.app.state.ctx
    cfg = ctx.settings.conn("proxmox").config
    assert cfg["token_secret"] == "very-secret-value" and cfg["backup_storage"] == "nas"
    assert "very-secret-value" not in ctx.db.kv_get("settings")  # 암호화 저장

    listed = client.get("/api/connections").json()
    assert [x["category"] for x in listed] == ["infra", "infra"]
    assert all(x["config"]["token_secret"] == MASK for x in listed)

    assert client.delete("/api/connections/proxmox-2").status_code == 200
    assert client.delete("/api/connections/proxmox-2").status_code == 404
    assert [x["id"] for x in client.get("/api/connections").json()] == ["proxmox"]


def test_connection_validation(client):
    bad = client.post("/api/connections", json={"type": "proxmox", "config": {"url": "192.168.0.5", "token_id": "a", "token_secret": "s"}})
    assert bad.status_code == 422 and "http://" in bad.json()["detail"]
    missing = client.post("/api/connections", json={"type": "proxmox", "config": {"url": "https://x", "token_id": "a"}})
    assert missing.status_code == 422 and "토큰 Secret" in missing.json()["detail"]
    assert client.post("/api/connections", json={"type": "nope", "config": {}}).status_code == 400


def test_alerts_and_backup_sections(client):
    assert client.put("/api/settings/alerts", json={"battery_warn": 25}).json()["alerts"]["battery_warn"] == 25
    assert client.put("/api/settings/alerts", json={"battery_warn": 0}).status_code == 422
    assert client.put("/api/settings/backup", json={"password": "pw1", "schedule_time": "25:00"}).status_code == 422


def test_migrates_old_settings(runtime):
    """v0.5 이하 형식(시스템별 키)을 열면 연결 목록으로 옮긴다. 비밀값도 유지."""
    c = make_client(Settings(), runtime)
    store = c.app.state.ctx.store
    old = {
        "hubitat": [{"id": "main", "name": "Main", "url": "http://192.168.0.80", "role": "자동화",
                     "maker_api": {"app_id": 7, "token": store._enc("hub-token")}, "login": None}],
        "home_assistant": {"url": "http://ha:8123", "token": store._enc("ha-token"), "verify_ssl": True},
        "alerts": {"battery_warn": 20},
    }
    c.app.state.ctx.db.kv_set("settings", json.dumps(old))
    s = store.load()
    assert [(x.id, x.type) for x in s.connections] == [("main", "hubitat"), ("home-assistant", "home_assistant")]
    assert s.conn("main").config["token"] == "hub-token" and s.conn("main").config["app_id"] == 7
    assert s.conn("home-assistant").config["token"] == "ha-token"
    assert s.alerts.battery_warn == 20
    raw = json.loads(c.app.state.ctx.db.kv_get("settings"))
    assert "connections" in raw and "hubitat" not in raw and "hub-token" not in json.dumps(raw)


@respx.mock
def test_connection_test(client):
    base = "https://pve.test:8006/api2/json"
    respx.get(f"{base}/version").mock(return_value=httpx.Response(200, json={"data": {"version": "9.0.3"}}))
    respx.get(f"{base}/nodes").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get(f"{base}/cluster/resources").mock(return_value=httpx.Response(200, json={"data": []}))
    body = {"type": "proxmox", "config": {"url": "https://pve.test:8006", "token_id": "a@pve!b", "token_secret": "s"}}
    r = client.post("/api/connections/test", json=body).json()
    assert r["ok"] and "9.0.3" in r["message"]
    assert client.get("/api/connections").json() == []  # 시험만, 저장 안 함

    # 저장된 연결은 비밀값 없이 id로 시험
    client.post("/api/connections", json=body)
    r = client.post("/api/connections/test", json={"id": "proxmox", "config": {**body["config"], "token_secret": MASK}}).json()
    assert r["ok"]

    respx.get("https://ptn.test/api/status").mock(return_value=httpx.Response(401))
    r = client.post("/api/connections/test", json={"type": "portainer", "config": {"url": "https://ptn.test", "api_key": "k"}}).json()
    assert r["ok"] is False and "인증 실패" in r["message"]
