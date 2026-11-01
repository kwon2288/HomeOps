import httpx
import respx

from app.config import HubitatCfg, Settings
from app.connectors.hubitat import normalize_device
from app.connectors.portainer import strip_docker_log

from .conftest import conn, make_client

HUB = conn("hubitat", "main", name="Hubitat Main", url="http://hub.test", app_id=7, token="tok")


# ---- 로그인 ----

def test_api_requires_login(runtime):
    c = make_client(Settings(), runtime, login=False)
    assert c.get("/api/status").status_code == 401
    assert c.get("/api/backup").status_code == 401
    assert c.get("/api/health").status_code == 200
    assert c.get("/").status_code == 200  # 정적 화면은 열림


def test_login_lockout(runtime):
    c = make_client(Settings(), runtime, login=False)
    for _ in range(5):
        assert c.post("/api/auth/login", json={"username": "admin", "password": "x"}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "admin", "password": "pw"}).status_code == 429


def test_login_ok(client):
    assert client.get("/api/auth/me").json()["user"] == "admin"


# ---- 빈 상태 · 수동 등록 ----

def test_starts_empty_and_crud(client):
    assert client.get("/api/connections").json() == []
    assert client.get("/api/status").json() == []
    assert client.get("/api/registry/devices").json() == []
    assert client.get("/api/registry/platforms").json() == []
    assert client.get("/api/registry/paths").json() == []
    sm = client.get("/api/smarthome").json()
    assert sm["sources"] == [] and sm["devices"] == [] and sm["paths"] == [] and sm["alerts"] == []

    r = client.post("/api/registry/devices", json={"name": "테스트 허브", "platform": "Aqara", "ip": "192.168.0.50",
                                                   "roles": ["Matter 브리지"]})
    new = r.json()
    assert new["roles"] == ["Matter 브리지"]
    assert client.put(f"/api/registry/devices/{new['id']}", json={**new, "memo": "메모"}).json()["memo"] == "메모"
    assert client.delete(f"/api/registry/devices/{new['id']}").status_code == 200
    assert client.delete(f"/api/registry/devices/{new['id']}").status_code == 404


def test_rejects_bad_ip(client):
    assert client.post("/api/registry/devices", json={"name": "x", "ip": "1.2.3.4; rm -rf /"}).status_code == 422


# ---- 연동 목록 (플러그인 자동 등록) ----

def test_integrations_listed(client):
    types = {m["type"]: m for m in client.get("/api/integrations").json()}
    for t in ("hubitat", "home_assistant", "homebridge", "synology", "proxmox", "portainer", "unifi", "vmware", "web"):
        assert t in types
    assert types["unifi"]["category"] == "infra" and types["hubitat"]["devices"] is True
    assert any(f["secret"] for f in types["unifi"]["fields"])


# ---- 위험 작업은 확인 필요 ----

@respx.mock
def test_reboot_needs_confirm_and_is_logged(runtime):
    respx.get("http://hub.test/hub2/hubData").mock(return_value=httpx.Response(200, json={}))
    respx.post("http://hub.test/hub/reboot").mock(return_value=httpx.Response(200))
    c = make_client(Settings(connections=[HUB]), runtime)
    assert c.post("/api/connections/main/actions/reboot", json={}).status_code == 400
    r = c.post("/api/connections/main/actions/reboot", json={"confirm": True})
    assert r.status_code == 200 and "재부팅" in r.json()["message"]
    log = c.get("/api/audit").json()
    assert log[0]["action"] == "reboot" and log[0]["result"] == "성공"


# ---- 커넥터 ----

def test_normalize_hubitat_device():
    hub = HubitatCfg(id="main", name="Main", url="http://hub.test")
    sw = normalize_device(hub, {"id": "28", "label": "거실등", "room": "거실",
                                "attributes": {"switch": "on"}, "commands": ["on", "off", "refresh"]})
    assert sw["is_switch"] and sw["on"] and sw["room"] == "거실" and sw["hub"] == "main"
    door = normalize_device(hub, {"id": "9", "label": "서재문", "attributes": {"contact": "open", "battery": "100"}, "commands": []})
    assert not door["is_switch"] and door["state_label"] == "열림" and door["contact_open"] and door["battery"] == 100


def test_strip_docker_log():
    frame = b"\x01\x00\x00\x00\x00\x00\x00\x06hello\n" + b"\x02\x00\x00\x00\x00\x00\x00\x04err\n"
    assert strip_docker_log(frame) == "hello\nerr\n"
    assert strip_docker_log(b"plain tty log") == "plain tty log"


@respx.mock
def test_status_proxmox_card(runtime):
    base = "https://pve.test:8006/api2/json"
    respx.get(f"{base}/version").mock(return_value=httpx.Response(200, json={"data": {"version": "9.0.3"}}))
    respx.get(f"{base}/nodes").mock(return_value=httpx.Response(200, json={"data": [
        {"node": "pve", "status": "online", "cpu": 0.12, "mem": 4e9, "maxmem": 16e9, "disk": 2e10, "maxdisk": 1e11, "uptime": 90000}]}))
    respx.get(f"{base}/cluster/resources").mock(return_value=httpx.Response(200, json={"data": [
        {"node": "pve", "type": "lxc", "vmid": 105, "name": "wikijs-mcp", "status": "running", "cpu": 0.01, "mem": 1e8, "maxmem": 1e9},
        {"node": "pve", "type": "qemu", "vmid": 100, "name": "haos", "status": "stopped", "maxmem": 4e9},
        {"node": "pve", "type": "qemu", "vmid": 900, "name": "tmpl", "status": "stopped", "template": 1}]}))
    pve = conn("proxmox", "proxmox", url="https://pve.test:8006", token_id="a@pve!b", token_secret="s")
    c = make_client(Settings(connections=[pve]), runtime)
    assert c.get("/api/status?category=smarthome").json() == []
    st = c.get("/api/status?category=infra").json()[0]
    assert st["online"] and "PVE 9.0.3" in st["card"]["summary"]
    rows = st["card"]["sections"][0]["rows"]
    assert [r["name"] for r in rows] == ["wikijs-mcp", "haos"]  # 실행 중 먼저, 템플릿 제외
    assert [a["id"] for a in rows[1]["actions"]][0] == "start"
    assert respx.calls[0].request.headers["Authorization"] == "PVEAPIToken=a@pve!b=s"


@respx.mock
def test_status_error_is_contained(runtime):
    respx.get("https://ptn.test/api/status").mock(return_value=httpx.Response(401))
    ptn = conn("portainer", "portainer", url="https://ptn.test", api_key="k")
    st = make_client(Settings(connections=[ptn]), runtime).get("/api/status").json()[0]
    assert st["online"] is False and "인증 실패" in st["error"]


@respx.mock
def test_unifi_status_and_restart(runtime):
    base = "https://udr.test/proxy/network/integration/v1"
    respx.get(f"{base}/info").mock(return_value=httpx.Response(200, json={"applicationVersion": "9.4.19"}))
    respx.get(f"{base}/sites").mock(return_value=httpx.Response(200, json={
        "offset": 0, "limit": 200, "count": 1, "totalCount": 1, "data": [{"id": "s-1", "name": "Default", "internalReference": "default"}]}))
    respx.get(f"{base}/sites/s-1/devices").mock(return_value=httpx.Response(200, json={
        "offset": 0, "limit": 200, "count": 2, "totalCount": 2, "data": [
            {"id": "d-1", "name": "UDR", "model": "UDR", "ipAddress": "192.168.0.1", "state": "ONLINE"},
            {"id": "d-2", "name": "거실 AP", "model": "U6-Lite", "ipAddress": "192.168.0.20", "state": "OFFLINE"}]}))
    respx.get(f"{base}/sites/s-1/clients").mock(return_value=httpx.Response(200, json={"totalCount": 57, "data": []}))
    restart = respx.post(f"{base}/sites/s-1/devices/d-2/actions").mock(return_value=httpx.Response(200, json={}))
    uni = conn("unifi", "unifi", url="https://udr.test", api_key="key")
    c = make_client(Settings(connections=[uni]), runtime)
    st = c.get("/api/status").json()[0]
    assert st["online"], st
    assert "Network 9.4.19" in st["card"]["summary"]
    m = {x["label"]: x["value"] for x in st["card"]["metrics"]}
    assert m["클라이언트"] == "57" and m["온라인"] == "1 / 2"
    assert st["card"]["sections"][0]["rows"][0]["name"] == "거실 AP"  # 오프라인 먼저
    assert respx.calls[0].request.headers["X-API-Key"] == "key"
    assert c.post("/api/connections/unifi/actions/restart", json={"params": {"device": "d-2"}}).status_code == 400
    r = c.post("/api/connections/unifi/actions/restart", json={"params": {"device": "d-2"}, "confirm": True})
    assert r.status_code == 200 and restart.called
    assert restart.calls[0].request.content == b'{"action":"RESTART"}'


@respx.mock
def test_vcenter_status_and_power(runtime):
    vc = "https://vc.test"
    respx.post(f"{vc}/api/session").mock(return_value=httpx.Response(201, json="sess-123"))
    respx.delete(f"{vc}/api/session").mock(return_value=httpx.Response(204))
    respx.get(f"{vc}/api/vcenter/host").mock(return_value=httpx.Response(200, json=[
        {"host": "host-1", "name": "esxi01", "connection_state": "CONNECTED", "power_state": "POWERED_ON"}]))
    respx.get(f"{vc}/api/vcenter/vm").mock(return_value=httpx.Response(200, json=[
        {"vm": "vm-10", "name": "db01", "power_state": "POWERED_OFF", "cpu_count": 2, "memory_size_MiB": 4096},
        {"vm": "vm-11", "name": "web01", "power_state": "POWERED_ON", "cpu_count": 4, "memory_size_MiB": 8192}]))
    power = respx.post(f"{vc}/api/vcenter/vm/vm-10/power").mock(return_value=httpx.Response(204))
    guest = respx.post(f"{vc}/api/vcenter/vm/vm-11/guest/power").mock(return_value=httpx.Response(204))
    v = conn("vmware", "vmware", url=vc, username="u@vsphere.local", password="p")
    c = make_client(Settings(connections=[v]), runtime)
    st = c.get("/api/status").json()[0]
    assert st["online"] and st["card"]["summary"] == "호스트 1대 · VM 2개"
    vm_rows = st["card"]["sections"][1]["rows"]
    assert vm_rows[0]["name"] == "web01" and vm_rows[0]["badge"] == "켜짐"
    assert c.post("/api/connections/vmware/actions/start", json={"params": {"vm": "vm-10"}}).status_code == 200
    assert power.calls[0].request.url.params["action"] == "start"
    assert power.calls[0].request.headers["vmware-api-session-id"] == "sess-123"
    assert c.post("/api/connections/vmware/actions/shutdown", json={"params": {"vm": "vm-11"}}).status_code == 400
    assert c.post("/api/connections/vmware/actions/shutdown", json={"params": {"vm": "vm-11"}, "confirm": True}).status_code == 200
    assert guest.calls[0].request.url.params["action"] == "shutdown"
    assert c.post("/api/connections/vmware/actions/start", json={"params": {"vm": "../x"}}).status_code == 400


@respx.mock
def test_web_check(runtime):
    respx.get("https://printer.test").mock(return_value=httpx.Response(401))
    respx.get("https://dead.test").mock(side_effect=httpx.ConnectError("x"))
    c = make_client(Settings(connections=[conn("web", "printer", url="https://printer.test", group="smarthome"),
                                          conn("web", "dead", url="https://dead.test")]), runtime)
    sm = c.get("/api/status?category=smarthome").json()
    assert [x["id"] for x in sm] == ["printer"] and sm[0]["online"] and sm[0]["link"] == "https://printer.test"
    dead = c.get("/api/status?category=infra").json()[0]
    assert dead["online"] is False and "응답 없음" in dead["error"]


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

    c = make_client(Settings(connections=[HUB]), runtime)
    c.post("/api/registry/paths", json={"src": "SmartThings", "via": "HubiThings Replica", "dst": "Hubitat Main", "check_ref": "main"})
    c.post("/api/registry/paths", json={"src": "옛 경로", "dst": "Hubitat", "check_ref": "hubitat:main"})  # 예전 표기
    d = c.get("/api/smarthome").json()
    assert d["mode"] == "Away" and d["hsm"] == "armedAway"
    assert [s["id"] for s in d["sources"]] == ["main"] and len(d["devices"]) == 3
    titles = [a["title"] for a in d["alerts"]]
    assert any("배터리" in t for t in titles) and any("열린 문 1곳" in t for t in titles)
    assert [p["status"] for p in d["paths"]] == ["ok", "ok"]

    assert c.post("/api/smarthome/devices/main/1/on").status_code == 200 and on.called
    assert c.post("/api/smarthome/devices/main/1;x/on").status_code in (400, 404)
    assert c.post("/api/smarthome/devices/nope/1/on").status_code == 404


@respx.mock
def test_hubitat_unreachable_says_why(runtime):
    """허브에 안 닿으면 여러 요청을 기다리다 '시간 초과'로 끝나지 않고 이유를 바로 알려 준다."""
    probe = respx.get("http://hub.test/hub2/hubData").mock(side_effect=httpx.ConnectTimeout("x"))
    c = make_client(Settings(connections=[HUB]), runtime)
    r = c.post("/api/connections/test", json={"id": "main", "config": {"url": "http://hub.test", "app_id": 7}}).json()
    assert r["ok"] is False and "연결을 받지 않습니다" in r["message"] and "hub.test" in r["message"]
    assert probe.call_count == 1 and len(respx.calls) == 1   # 다른 요청은 하지 않음
    st = c.get("/api/status").json()[0]
    assert st["online"] is False and "IP 주소가 맞는지" in st["error"]

    probe.mock(side_effect=httpx.ReadTimeout("x"))
    r = c.post("/api/connections/test", json={"id": "main", "config": {"url": "http://hub.test", "app_id": 7}}).json()
    assert "연결은 됐지만" in r["message"]
    probe.mock(side_effect=httpx.ConnectError("refused"))
    r = c.post("/api/connections/test", json={"id": "main", "config": {"url": "http://hub.test", "app_id": 7}}).json()
    assert "주소와 포트" in r["message"]


@respx.mock
def test_hubitat_with_hub_login(runtime):
    """허브 로그인을 켠 허브: 로그인 후 같은 연결로 관리 URL 호출 (예전에는 연결 재사용 오류)."""
    respx.get("http://hub.test/hub2/hubData").mock(return_value=httpx.Response(200, json={"firmwareVersionString": "2.4.3"}))
    login = respx.post("http://hub.test/login").mock(return_value=httpx.Response(200))
    respx.get(url__regex=r"http://hub\.test/hub/advanced/.*").mock(return_value=httpx.Response(200, text="512000"))
    reboot = respx.post("http://hub.test/hub/reboot").mock(return_value=httpx.Response(200))
    hub = conn("hubitat", "main", url="http://hub.test", login_user="admin", login_password="pw")
    c = make_client(Settings(connections=[hub]), runtime)
    st = c.get("/api/status").json()[0]
    assert st["online"], st
    assert c.post("/api/connections/main/actions/reboot", json={"confirm": True}).status_code == 200
    assert login.call_count == 2 and reboot.call_count == 1
