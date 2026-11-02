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


@respx.mock
def test_synology_two_factor_device_token(client):
    """2단계 인증 계정: OTP로 한 번 로그인 → 기기 ID 저장 → 이후 코드 없이 로그인."""
    nas = "https://nas.test:5001"
    seen = []

    def auth(request):
        p = dict(request.url.params)
        seen.append(p)
        if p.get("method") == "logout":
            return httpx.Response(200, json={"success": True})
        if p.get("otp_code") == "123456" and p.get("enable_device_token") == "yes":
            # DSM 7 형식 (device_id). DSM 6 은 did
            return httpx.Response(200, json={"success": True, "data": {"sid": "s1", "device_id": "dev-abc"}})
        if p.get("otp_code"):
            return httpx.Response(200, json={"success": False, "error": {"code": 404}})
        if p.get("device_id") == "dev-abc":
            return httpx.Response(200, json={"success": True, "data": {"sid": "s2"}})
        return httpx.Response(200, json={"success": False, "error": {"code": 403}})

    def entry(request):
        api = request.url.params["api"]
        if api == "SYNO.Core.System":
            return httpx.Response(200, json={"success": True, "data": {"model": "DS920+", "firmware_ver": "DSM 7.2.2"}})
        if api == "SYNO.Core.System.Utilization":
            return httpx.Response(200, json={"success": True, "data": {"cpu": {"user_load": 5}, "memory": {"real_usage": 40}}})
        return httpx.Response(200, json={"success": True, "data": {"volumes": [], "disks": []}})

    respx.get(f"{nas}/webapi/auth.cgi").mock(side_effect=auth)
    respx.get(f"{nas}/webapi/entry.cgi").mock(side_effect=entry)
    base = {"type": "synology", "name": "NAS", "config": {"url": nas, "username": "min", "password": "pw"}}

    # 코드 없이: 2단계 인증 필요 안내
    r = client.post("/api/connections/test", json=base).json()
    assert r["ok"] is False and "2단계 인증 코드" in r["message"]
    # 틀린 코드
    bad = client.post("/api/connections/test", json={**base, "config": {**base["config"], "otp_code": "000000"}}).json()
    assert bad["ok"] is False and "맞지 않거나" in bad["message"]
    # 맞는 코드로 테스트 → 이어서 저장 (같은 코드를 다시 쓰지 않고 받아 둔 기기 ID 사용)
    with_otp = {**base, "config": {**base["config"], "otp_code": "123456"}}
    r = client.post("/api/connections/test", json=with_otp).json()
    assert r["ok"] and "2단계 인증 확인됨" in r["message"]
    n_before = len(seen)
    saved = client.post("/api/connections", json=with_otp)
    assert saved.status_code == 200, saved.text
    assert len(seen) == n_before  # 저장 때 OTP 로그인을 다시 하지 않음
    cfg = client.app.state.ctx.settings.conn("synology").config
    assert cfg["device_id"] == "dev-abc" and cfg["otp_code"] == ""
    assert saved.json()["config"]["device_id"] == MASK

    # 이후 상태 조회는 기기 ID로 로그인
    st = client.get("/api/status").json()[0]
    assert st["online"], st
    logins = [p for p in seen if p.get("method") == "login"]
    assert logins[-1].get("device_id") == "dev-abc" and "otp_code" not in logins[-1]

    # 편집해서 이름만 바꿔도 기기 ID 유지
    client.put("/api/connections/synology", json={"name": "NAS 2", "config": {"url": nas, "username": "min"}})
    assert client.app.state.ctx.settings.conn("synology").config["device_id"] == "dev-abc"

    # 테스트 없이 바로 저장해도 등록됨
    client.delete("/api/connections/synology")
    saved = client.post("/api/connections", json=with_otp)
    assert saved.status_code == 200 and client.app.state.ctx.settings.conn("synology").config["device_id"] == "dev-abc"


def test_dashboard_layout(client):
    assert client.get("/api/layout/infra").json() == {"height": "m", "order": [], "cards": {}}
    body = {"order": ["proxmox", "synology"], "cards": {"proxmox": {"size": "l", "rows": 3}, "synology": {"hidden": True}}}
    saved = client.put("/api/layout/infra", json=body).json()
    assert saved["cards"]["proxmox"] == {"size": "l", "rows": 3, "hidden": False}
    assert client.get("/api/layout/infra").json() == saved
    assert client.get("/api/layout/hubs").json()["order"] == []          # 화면마다 따로
    assert client.put("/api/layout/infra", json={"cards": {"x": {"rows": 7}}}).status_code == 422
    assert client.put("/api/layout/infra", json={"height": "auto"}).json()["height"] == "auto"
    assert client.put("/api/layout/infra", json={"height": "huge"}).status_code == 422
    assert client.put("/api/layout/nope", json={}).status_code == 404
    assert client.get("/api/status/nope").status_code == 404


def test_hub_backup_delete_and_manual_layout(client):
    d = client.app.state.ctx.runtime.backup_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "main-20261102-010101.lzf").write_bytes(b"x")
    (d / "keep.txt").write_bytes(b"x")
    assert [x["file"] for x in client.get("/api/hub-backups").json()] == ["main-20261102-010101.lzf"]
    assert client.delete("/api/hub-backups/main-20261102-010101.lzf").status_code == 200
    assert client.get("/api/hub-backups").json() == []
    assert client.delete("/api/hub-backups/main-20261102-010101.lzf").status_code == 404
    assert client.delete("/api/hub-backups/keep.txt").status_code == 400          # .lzf 만
    assert client.delete("/api/hub-backups/..%2Fhomeops.db").status_code in (400, 404, 405)
    assert (d / "keep.txt").exists() and client.app.state.ctx.runtime.db_path.exists()
    assert client.get("/api/audit").json()[0]["action"] == "Hubitat 백업 파일 삭제"

    saved = client.put("/api/layout/manual", json={"order": ["3", "1"], "cards": {"1": {"hidden": True, "size": "l"}}}).json()
    assert saved["order"] == ["3", "1"] and saved["cards"]["1"]["hidden"]
