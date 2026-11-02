import json

import httpx
import respx

from app.config import Settings

from .conftest import conn, make_client

H = "http://homey.test/api/manager"
DEVICES = {
    "d-wash": {"id": "d-wash", "name": "세탁기", "zone": "z-util", "class": "washer", "available": True,
               "driverId": "homey:app:com.lgthinq:washer", "capabilities": ["onoff", "measure_power"],
               "capabilitiesObj": {"onoff": {"value": False, "setable": True}, "measure_power": {"value": 3}}},
    "d-ac": {"id": "d-ac", "name": "거실 에어컨", "zone": "z-living", "class": "airconditioner", "available": False,
             "unavailableMessage": "ThinQ 연결 끊김", "driverId": "homey:app:com.lgthinq:ac",
             "capabilities": ["onoff"], "capabilitiesObj": {"onoff": {"value": True, "setable": True}}},
    "d-temp": {"id": "d-temp", "name": "베란다 온도", "zone": "z-living", "class": "sensor", "available": True,
               "driverId": "homey:app:com.tuya:sensor", "capabilities": ["measure_temperature", "measure_battery"],
               "capabilitiesObj": {"measure_temperature": {"value": 12.5}, "measure_battery": {"value": 9}}},
}


def mock(seen):
    def auth(request):
        assert request.headers["Authorization"] == "Bearer key"
        seen.append(request)
    respx.get(f"{H}/devices/device/").mock(side_effect=lambda r: (auth(r), httpx.Response(200, json=DEVICES))[1])
    respx.get(f"{H}/zones/zone/").mock(return_value=httpx.Response(200, json={
        "z-util": {"id": "z-util", "name": "다용도실"}, "z-living": {"id": "z-living", "name": "거실"}}))
    respx.get(f"{H}/system/").mock(return_value=httpx.Response(403))   # 키에 시스템 권한 없음
    respx.get(f"{H}/flow/flow/").mock(return_value=httpx.Response(200, json={"f1": {"id": "f1", "name": "외출", "enabled": True}}))
    respx.get(f"{H}/flow/advancedflow/").mock(return_value=httpx.Response(200, json={"a1": {"id": "a1", "name": "취침", "enabled": True}}))
    respx.put(url__regex=rf"{H}/devices/device/[^/]+/capability/onoff/").mock(side_effect=lambda r: (auth(r), httpx.Response(200, json={}))[1])
    respx.post(url__regex=rf"{H}/flow/(flow|advancedflow)/[^/]+/trigger").mock(side_effect=lambda r: (auth(r), httpx.Response(200, json={}))[1])


@respx.mock
def test_homey_lg_filter_card_and_controls(runtime):
    seen = []
    mock(seen)
    lg = conn("homey", "homey", url="http://homey.test", api_key="key", app_filter="lg", show_flows=True)
    c = make_client(Settings(connections=[lg]), runtime)
    r = c.post("/api/connections/test", json={"id": "homey", "config": {"url": "http://homey.test", "app_filter": "lg", "show_flows": True}}).json()
    assert r["ok"] and "기기 2개 (전체 3개 중 'lg' 앱)" in r["message"] and "LG ThinQ" in r["message"], r

    card = c.get("/api/status/homey").json()["card"]
    rows = card["sections"][0]["rows"]
    assert [x["name"] for x in rows] == ["거실 에어컨", "세탁기"]          # 응답 없는 것 먼저
    assert rows[0]["badge"] == "ThinQ 연결 끊김" and rows[0]["actions"] == []
    assert rows[1]["badge"] == "꺼짐" and "다용도실 · LG ThinQ · washer" in rows[1]["note"]
    assert [x["name"] for x in card["sections"][1]["rows"]] == ["외출", "취침"]

    devs = {d["id"]: d for d in c.get("/api/smarthome").json()["devices"]}
    assert set(devs) == {"d-wash", "d-ac"} and devs["d-wash"]["room"] == "다용도실" and devs["d-wash"]["source"] == "HY"
    assert devs["d-wash"]["is_switch"] and not devs["d-ac"]["is_switch"]

    assert c.post("/api/smarthome/devices/homey/d-wash/on").status_code == 200
    assert json.loads(seen[-1].content) == {"value": True}               # JSON (문자열이 아니라 진짜 true)
    assert c.post("/api/connections/homey/actions/flow", json={"params": {"id": "a1", "kind": "advancedflow"}}).status_code == 200
    assert seen[-1].url.path.endswith("/flow/advancedflow/a1/trigger")
    assert c.post("/api/connections/homey/actions/turn-off", json={"params": {"id": "../x"}}).status_code == 400


@respx.mock
def test_homey_all_devices_and_bad_key(runtime):
    mock([])
    c = make_client(Settings(connections=[conn("homey", "homey", url="http://homey.test", api_key="key")]), runtime)
    card = c.get("/api/status/homey").json()["card"]
    assert len(card["sections"]) == 1 and len(card["sections"][0]["rows"]) == 3   # 플로우는 기본 숨김
    assert "베란다 온도 9%" in card["note"]
    respx.get(f"{H}/devices/device/").mock(return_value=httpx.Response(401))
    r = c.post("/api/connections/test", json={"id": "homey", "config": {"url": "http://homey.test"}}).json()
    assert r["ok"] is False and "API 키" in r["message"]
