import httpx
import respx

from app.config import Settings
from app.store import MASK

from .conftest import make_client


def test_first_run_setup(web_runtime):
    c = make_client(Settings(), web_runtime, login=False)
    assert c.get("/api/auth/status").json()["needs_setup"] is True
    assert c.post("/api/auth/login", json={"username": "admin", "password": "x"}).status_code == 409
    assert c.post("/api/auth/setup", json={"username": "min", "password": "short"}).status_code == 422

    r = c.post("/api/auth/setup", json={"username": "min", "password": "longenough1"})
    assert r.status_code == 200
    assert c.get("/api/auth/me").json()["user"] == "min"  # 만들자마자 로그인됨
    assert c.get("/api/auth/status").json()["needs_setup"] is False
    assert c.post("/api/auth/setup", json={"username": "x", "password": "longenough1"}).status_code == 409

    c.post("/api/auth/logout")
    assert c.post("/api/auth/login", json={"username": "min", "password": "wrong-pass"}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "min", "password": "longenough1"}).status_code == 200

    assert c.post("/api/auth/password", json={"current": "nope", "new": "newpassword1"}).status_code == 400
    assert c.post("/api/auth/password", json={"current": "longenough1", "new": "newpassword1"}).status_code == 200
    c.post("/api/auth/logout")
    assert c.post("/api/auth/login", json={"username": "min", "password": "newpassword1"}).status_code == 200


def test_secrets_masked_kept_and_encrypted(runtime):
    c = make_client(Settings(), runtime)
    body = {"url": "https://pve.test:8006", "token_id": "a@pve!b", "token_secret": "very-secret-value", "verify_ssl": False}
    r = c.put("/api/settings/proxmox", json=body)
    assert r.status_code == 200
    assert r.json()["proxmox"]["token_secret"] == MASK

    # 비밀값을 MASK 그대로 보내면 기존 값 유지
    r = c.put("/api/settings/proxmox", json={**body, "token_secret": MASK, "backup_storage": "nas"})
    ctx = c.app.state.ctx
    assert ctx.settings.proxmox.token_secret == "very-secret-value"
    assert ctx.settings.proxmox.backup_storage == "nas"

    raw = ctx.db.kv_get("settings")
    assert "very-secret-value" not in raw  # DB에는 암호화되어 저장

    # 지우기
    assert c.put("/api/settings/proxmox", json=None).json()["proxmox"] is None
    assert c.put("/api/settings/alerts", json=None).status_code == 400


def test_hubitat_list(runtime):
    c = make_client(Settings(), runtime)
    hub = {"id": "main", "name": "Main", "url": "http://192.168.0.80", "maker_api": {"app_id": 7, "token": "tok1"}}
    assert c.put("/api/settings/hubitat", json=[hub]).status_code == 200
    # ID를 바꿔도 orig_id로 토큰 유지
    renamed = {**hub, "id": "auto", "orig_id": "main", "maker_api": {"app_id": 7, "token": MASK}}
    assert c.put("/api/settings/hubitat", json=[renamed]).status_code == 200
    assert c.app.state.ctx.settings.hub("auto").maker_api.token == "tok1"

    assert c.put("/api/settings/hubitat", json=[hub, {**hub}]).status_code == 400  # ID 중복
    bad = c.put("/api/settings/hubitat", json=[{**hub, "url": "192.168.0.80"}])
    assert bad.status_code == 422 and "주소" in bad.json()["detail"]


@respx.mock
def test_connection_test(runtime):
    base = "https://pve.test:8006/api2/json"
    respx.get(f"{base}/version").mock(return_value=httpx.Response(200, json={"data": {"version": "9.0.3"}}))
    respx.get(f"{base}/nodes").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get(f"{base}/cluster/resources").mock(return_value=httpx.Response(200, json={"data": []}))
    c = make_client(Settings(), runtime)
    body = {"url": "https://pve.test:8006", "token_id": "a@pve!b", "token_secret": "s"}
    r = c.post("/api/settings/test/proxmox", json=body).json()
    assert r["ok"] and "9.0.3" in r["message"]
    assert c.app.state.ctx.settings.proxmox is None  # 시험만 하고 저장은 안 함

    respx.get("https://ptn.test/api/status").mock(return_value=httpx.Response(401))
    r = c.post("/api/settings/test/portainer", json={"url": "https://ptn.test", "api_key": "k"}).json()
    assert r["ok"] is False and "인증 실패" in r["message"]
