import base64
import hashlib
import hmac
import json

import httpx
import pytest
import respx

from app.config import Settings
from app.connectors import switchbot as sbc

from .conftest import conn, make_client

API = "https://api.switch-bot.com/v1.1"

DEVICES = {
    "deviceList": [
        {"deviceId": "HUB1", "deviceName": "거실 허브2", "deviceType": "Hub 2", "enableCloudService": True, "hubDeviceId": "HUB1"},
        {"deviceId": "BOT1", "deviceName": "보일러 Bot", "deviceType": "Bot", "enableCloudService": True, "hubDeviceId": "HUB1"},
        {"deviceId": "CUR1", "deviceName": "거실 커튼", "deviceType": "Curtain3", "enableCloudService": True, "hubDeviceId": "HUB1"},
        {"deviceId": "LOCK1", "deviceName": "현관", "deviceType": "Smart Lock Pro", "enableCloudService": True, "hubDeviceId": "HUB1"},
        {"deviceId": "MET1", "deviceName": "침실 온습도", "deviceType": "Meter Plus", "enableCloudService": True, "hubDeviceId": "HUB1"},
        {"deviceId": "PLG1", "deviceName": "전기장판", "deviceType": "Plug Mini (JP)", "enableCloudService": True, "hubDeviceId": "000000000000"},
        {"deviceId": "OFF1", "deviceName": "베란다 센서", "deviceType": "Contact Sensor", "enableCloudService": True, "hubDeviceId": "HUB1"},
        {"deviceId": "NOC1", "deviceName": "클라우드 꺼짐", "deviceType": "Bot", "enableCloudService": False, "hubDeviceId": "HUB1"},
    ],
    "infraredRemoteList": [{"deviceId": "02-IR1", "deviceName": "거실 TV", "remoteType": "TV", "hubDeviceId": "HUB1"}],
}
STATUS = {
    "HUB1": {"temperature": 23.5, "humidity": 45},
    "BOT1": {"power": "off", "battery": 12},
    "CUR1": {"slidePosition": 100, "battery": 80},
    "LOCK1": {"lockState": "unlocked", "battery": 90},
    "MET1": {"temperature": 21.2, "humidity": 55, "battery": 64},
    "PLG1": {"power": "on"},
}


def ok(body):
    return httpx.Response(200, json={"statusCode": 100, "message": "success", "body": body})


@pytest.fixture(autouse=True)
def clean_cache():
    sbc._cache.clear()
    sbc._calls.clear()


def mock_api(seen):
    def check_sign(request):
        h = request.headers
        expected = base64.b64encode(hmac.new(b"sec", f"tok{h['t']}{h['nonce']}".encode(), hashlib.sha256).digest()).decode()
        assert h["Authorization"] == "tok" and h["sign"] == expected and len(h["t"]) == 13
        seen.append(request)

    def devices(request):
        check_sign(request)
        return ok(DEVICES)

    def status(request, did):
        check_sign(request)
        if did == "OFF1":
            return httpx.Response(200, json={"statusCode": 161, "message": "device offline", "body": {}})
        return ok(STATUS[did])

    def command(request, did):
        check_sign(request)
        return ok({})

    respx.get(f"{API}/devices").mock(side_effect=devices)
    respx.get(url__regex=rf"{API}/devices/(?P<did>[^/]+)/status").mock(side_effect=status)
    respx.post(url__regex=rf"{API}/devices/(?P<did>[^/]+)/commands").mock(side_effect=command)
    respx.get(f"{API}/scenes").mock(side_effect=lambda r: (check_sign(r), ok([{"sceneId": "S1", "sceneName": "외출"}]))[1])
    respx.post(f"{API}/scenes/S1/execute").mock(side_effect=lambda r: (check_sign(r), ok({}))[1])


SB = conn("switchbot", "switchbot", name="SwitchBot", token="tok", secret="sec", status_minutes="5")


@respx.mock
def test_switchbot_status_card_and_cache(runtime):
    seen = []
    mock_api(seen)
    c = make_client(Settings(connections=[SB]), runtime)
    r = c.post("/api/connections/test", json={"id": "switchbot", "config": {"token": "__SET__", "secret": "__SET__"}}).json()
    assert r["ok"], r
    assert "기기 8개" in r["message"] and "IR 리모컨 1개" in r["message"] and "클라우드 서비스가 꺼진 기기 1개" in r["message"]

    st = c.get("/api/status/switchbot").json()
    assert st["online"], st
    card = st["card"]
    rows = {x["name"]: x for x in card["sections"][0]["rows"]}
    assert rows["보일러 Bot"]["badge"] == "꺼짐" and [a["id"] for a in rows["보일러 Bot"]["actions"]] == ["press", "turn-on", "turn-off"]
    assert rows["거실 커튼"]["badge"] == "닫힘"
    assert rows["현관"]["badge"] == "열림" and rows["현관"]["tone"] == "warn"
    assert rows["침실 온습도"]["badge"] == "21.2° · 55%"
    assert rows["베란다 센서"]["badge"] == "기기가 오프라인입니다"
    assert rows["클라우드 꺼짐"]["badge"] == "클라우드 꺼짐"
    # 문제 있는 것 먼저
    assert card["sections"][0]["rows"][0]["tone"] == "warn"
    metrics = {m["label"]: m["value"] for m in card["metrics"]}
    assert metrics["응답 없음"] == "1" and metrics["배터리 부족"] == "1"
    assert "보일러 Bot 12%" in card["note"]
    assert [s["title"] for s in card["sections"]] == ["기기 (문제 있는 것 먼저)", "IR 리모컨", "장면"]

    # 캐시: 다시 조회해도 API를 다시 부르지 않음 (하루 10,000회 한도)
    n = len(seen)
    c.get("/api/status/switchbot")
    c.get("/api/smarthome")
    assert len(seen) == n


@respx.mock
def test_switchbot_controls(runtime):
    seen = []
    mock_api(seen)
    c = make_client(Settings(connections=[SB]), runtime)
    devs = {d["id"]: d for d in c.get("/api/smarthome").json()["devices"]}
    assert devs["PLG1"]["is_switch"] and devs["PLG1"]["on"] and devs["PLG1"]["source"] == "SB"
    assert devs["MET1"]["state_label"] == "21.2° · 55%" and not devs["MET1"]["is_switch"]
    assert devs["OFF1"]["is_switch"] is False

    # 스마트홈 연동 화면의 켜기/끄기
    assert c.post("/api/smarthome/devices/switchbot/PLG1/off").status_code == 200
    body = json.loads(seen[-1].content)
    assert body == {"command": "turnOff", "parameter": "default", "commandType": "command"}

    # 상태 카드의 버튼
    act = lambda a, p, **kw: c.post(f"/api/connections/switchbot/actions/{a}", json={"params": p, **kw})
    assert act("press", {"id": "BOT1"}).status_code == 200 and json.loads(seen[-1].content)["command"] == "press"
    assert act("close", {"id": "CUR1"}).status_code == 200 and json.loads(seen[-1].content)["command"] == "turnOff"
    assert act("unlock", {"id": "LOCK1"}).status_code == 400            # 도어락 열기는 확인 필요
    assert act("unlock", {"id": "LOCK1"}, confirm=True).status_code == 200
    assert act("scene", {"scene": "S1"}).status_code == 200 and seen[-1].url.path.endswith("/scenes/S1/execute")
    assert act("press", {"id": "../x"}).status_code == 400


@respx.mock
def test_switchbot_auth_error(runtime):
    respx.get(f"{API}/devices").mock(return_value=httpx.Response(401, json={"message": "Unauthorized"}))
    c = make_client(Settings(connections=[SB]), runtime)
    r = c.post("/api/connections/test", json={"id": "switchbot", "config": {"token": "__SET__", "secret": "__SET__"}}).json()
    assert r["ok"] is False and "토큰 · 시크릿" in r["message"]
