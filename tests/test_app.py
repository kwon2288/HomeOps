from __future__ import annotations

import httpx
import respx

from app.config import Settings
from app.connectors.hubitat import normalize_device
from app.connectors.portainer import strip_docker_log

from .conftest import make_client

HUB = {"id": "main", "name": "Hubitat Main", "url": "http://hub.test",
       "maker_api": {"app_id": 7, "token": "tok"}}


# ---- 로그인 ----

def test_api_requires_login(runtime):
    c = make_client(Settings(), runtime, login=False)
    assert c.get("/api/infra").status_code == 401
    assert c.get("/api/backup").status_code == 401
    assert c.get("/api/health").status_code == 200
    assert c.get("/").status_code == 200  # 정적 화면은 열림


def test_login_lockout(runtime):
    c = make_client(Settings(), runtime, login=False)
    for _ in range(5):
        assert c.post("/api/auth/login", json={"username": "admin", "password": "x"}).status_code == 401
    r = c.post("/api/auth/login", json={"username": "admin", "password": "pw"})
    assert r.status_code == 429


def test_login_ok(client):
    assert client.get("/api/auth/me").json()["user"] == "admin"


# ---- 수동 등록 · 플랫폼 · 경로 ----

def test_seed_and_crud(client):
    devices = client.get("/api/registry/devices").json()
    assert any(d["name"] == "Apple TV 4K" for d in devices)
    assert client.get("/api/registry/platforms").json()
    assert client.get("/api/registry/paths").json()

    r = client.post("/api/registry/devices", json={
        "name": "테스트 허브", "platform": "Aqara", "ip": "192.168.0.50", "roles": ["Matter 브리지"]})
    assert r.status_code == 200
    new = r.json()
    assert new["roles"] == ["Matter 브리지"]

    r = client.put(f"/api/registry/devices/{new['id']}", json={**new, "memo": "메모"})
    assert r.json()["memo"] == "메모"
    assert client.delete(f"/api/registry/devices/{new['id']}").status_code == 200
    assert client.delete(f"/api/registry/devices/{new['id']}").status_code == 404


def test_rejects_bad_ip(client):
    r = client.post("/api/registry/devices", json={"name": "x", "ip": "1.2.3.4; rm -rf /"})
    assert r.status_code == 422


# ---- 위험 작업은 확인 필요 ----

def test_reboot_needs_confirm(runtime):
    c = make_client(Settings(hubitat=[HUB]), runtime)
    assert c.post("/api/hubs/hubitat/main/reboot").status_code == 400
    assert c.post("/api/hubs/hubitat/main/reboot", json={"confirm": False}).status_code == 400


@respx.mock
def test_reboot_with_confirm_is_logged(runtime):
    respx.post("http://hub.test/hub/reboot").mock(return_value=httpx.Response(200))
    c = make_client(Settings(hubitat=[HUB]), runtime)
    assert c.post("/api/hubs/hubitat/main/reboot", json={"confirm": True}).status_code == 200
    log = c.get("/api/audit").json()
    assert log[0]["action"] == "Hubitat 재부팅" and log[0]["result"] == "성공"


# ---- 커넥터 ----

def test_normalize_hubitat_device():
    from app.config import HubitatCfg
    hub = HubitatCfg(**HUB)
    sw = normalize_device(hub, {"id": "28", "label": "거실등", "room": "거실",
                                "attributes": {"switch": "on"}, "commands": ["on", "off", "refresh"]})
    assert sw["is_switch"] and sw["on"] and sw["room"] == "거실"
    door = normalize_device(hub, {"id": "9", "label": "서재문",
                                  "attributes": {"contact": "open", "battery": "100"}, "commands": []})
    assert not door["is_switch"] and door["state_label"] == "열림" and door["contact_open"]
    assert door["battery"] == 100


def test_strip_docker_log():
    frame = b"\x01\x00\x00\x00\x00\x00\x00\x06hello\n" + b"\x02\x00\x00\x00\x00\x00\x00\x04err\n"
    assert strip_docker_log(frame) == "hello\nerr\n"
    assert strip_docker_log(b"plain tty log") == "plain tty log"


@respx.mock
def test_infra_proxmox(runtime):
    base = "https://pve.test:8006/api2/json"
    respx.get(f"{base}/version").mock(return_value=httpx.Response(200, json={"data": {"version": "9.0.3"}}))
    respx.get(f"{base}/nodes").mock(return_value=httpx.Response(200, json={"data": [
        {"node": "pve", "status": "online", "cpu": 0.12, "mem": 4e9, "maxmem": 16e9, "disk": 2e10, "maxdisk": 1e11, "uptime": 90000}]}))
    respx.get(f"{base}/cluster/resources").mock(return_value=httpx.Response(200, json={"data": [
        {"node": "pve", "type": "lxc", "vmid": 105, "name": "wikijs-mcp", "status": "running", "cpu": 0.01, "mem": 1e8, "maxmem": 1e9},
        {"node": "pve", "type": "qemu", "vmid": 100, "name": "haos", "status": "stopped", "maxmem": 4e9},
        {"node": "pve", "type": "qemu", "vmid": 900, "name": "tmpl", "status": "stopped", "template": 1}]}))
    settings = Settings(proxmox={"url": "https://pve.test:8006", "token_id": "a@pve!b", "token_secret": "s"})
    c = make_client(settings, runtime)
    d = c.get("/api/infra").json()
    assert d["nas"]["configured"] is False
    pve = d["proxmox"]
    assert pve["online"] and pve["data"]["version"] == "9.0.3"
    assert [g["name"] for g in pve["data"]["guests"]] == ["wikijs-mcp", "haos"]  # 실행 중 먼저, 템플릿 제외
    assert pve["data"]["nodes"][0]["mem_pct"] == 25.0
    assert respx.calls[0].request.headers["Authorization"] == "PVEAPIToken=a@pve!b=s"


@respx.mock
def test_infra_error_is_contained(runtime):
    respx.get("https://ptn.test/api/status").mock(return_value=httpx.Response(401))
    settings = Settings(portainer={"url": "https://ptn.test", "api_key": "k"})
    d = make_client(settings, runtime).get("/api/infra").json()
    assert d["portainer"]["online"] is False
    assert "인증 실패" in d["portainer"]["error"]


@respx.mock
def test_smarthome_overview(runtime):
    api = "http://hub.test/apps/api/7"
    respx.get(f"{api}/devices/all").mock(return_value=httpx.Response(200, json=[
        {"id": "1", "label": "거실등", "room": "거실", "attributes": {"switch": "off"}, "commands": ["on", "off"]},
        {"id": "2", "label": "침실 버튼", "room": "침실", "attributes": {"battery": "12"}, "commands": []},
        {"id": "3", "label": "서재문", "room": "서재", "attributes": {"contact": "open"}, "commands": []},
    ]))
    respx.get(f"{api}/modes").mock(return_value=httpx.Response(200, json=[
        {"id": 1, "name": "Home", "active": False}, {"id": 2, "name": "Away", "active": True}]))
    respx.get(f"{api}/hsm").mock(return_value=httpx.Response(200, json={"hsm": "armedAway"}))
    respx.get(url__regex=r"http://hub\.test/hub.*").mock(return_value=httpx.Response(404))
    on = respx.get(f"{api}/devices/1/on").mock(return_value=httpx.Response(200, json={}))

    c = make_client(Settings(hubitat=[HUB]), runtime)
    d = c.get("/api/smarthome").json()
    assert d["mode"] == "Away" and d["hsm"] == "armedAway"
    assert len(d["devices"]) == 3
    titles = [a["title"] for a in d["alerts"]]
    assert any("배터리" in t for t in titles)
    assert any("열린 문 1곳" in t for t in titles)
    main_path = next(p for p in d["paths"] if p["check_ref"] == "hubitat:main")
    assert main_path["status"] == "ok"  # Maker API 응답으로 온라인 판정

    assert c.post("/api/smarthome/devices/HE/main/1/on").status_code == 200
    assert on.called
    assert c.post("/api/smarthome/devices/HE/main/1;x/on").status_code in (400, 404)
