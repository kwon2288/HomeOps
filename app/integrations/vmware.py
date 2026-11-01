"""VMware vCenter (vSphere Automation REST API, vCenter 7.0 U2 이상).

ESXi 단독 호스트는 이 REST API를 제공하지 않아 지원하지 않는다.
"""
from __future__ import annotations

import re

import httpx

from ..connectors.base import ConnectorError, make_client
from .base import Integration, act, card, field, metric, row, section, url_field, verify_field

SAFE_VM = re.compile(r"^vm-\d{1,10}$")
POWER = {"POWERED_ON": ("켜짐", "ok"), "POWERED_OFF": ("꺼짐", ""), "SUSPENDED": ("일시 정지", "warn")}


class VCenter(Integration):
    type = "vmware"
    title = "VMware vCenter"
    category = "infra"
    desc = "호스트 · VM 전원 · 게스트 종료/재시작"
    order = 50
    help = ("vCenter Server 7.0 U2 이상의 REST API를 씁니다. vCenter 웹 로그인 계정(예: <code>homeops@vsphere.local</code>)을 "
            "넣으세요. VM 전원을 제어하려면 계정에 가상 머신 → 상호 작용 → 전원 켜기/끄기 권한이 필요합니다. "
            "ESXi 단독 호스트는 아직 지원하지 않습니다.")
    fields = [
        url_field("https://vcenter.local"),
        field("username", "아이디", required=True, ph="homeops@vsphere.local"),
        field("password", "비밀번호", secret=True, required=True),
        verify_field(default=False),
    ]

    def confirm_required(self, action: str) -> bool:
        return action in {"stop", "shutdown", "reboot", "reset"}

    def _client(self) -> httpx.AsyncClient:
        return make_client(verify=self.cfg.get("verify_ssl", False), timeout=15)

    async def _session(self, c: httpx.AsyncClient) -> str:
        r = await c.post(self.cfg["url"] + "/api/session", auth=(self.cfg.get("username") or "", self.cfg.get("password") or ""))
        if r.status_code in (401, 403):
            raise ConnectorError("vCenter 로그인 실패 (아이디·비밀번호 확인)")
        if r.status_code == 404:
            raise ConnectorError("vCenter REST API(/api)를 찾지 못했습니다 (vCenter 7.0 U2 이상 필요)")
        r.raise_for_status()
        token = r.json()
        c.headers["vmware-api-session-id"] = token
        return token

    async def _end(self, c: httpx.AsyncClient) -> None:
        try:
            await c.delete(self.cfg["url"] + "/api/session")
        except httpx.HTTPError:
            pass

    async def _get(self, c: httpx.AsyncClient, path: str):
        r = await c.get(self.cfg["url"] + path)
        r.raise_for_status()
        return r.json()

    async def status(self) -> dict:
        async with self._client() as c:
            await self._session(c)
            try:
                hosts = await self._get(c, "/api/vcenter/host")
                vms = await self._get(c, "/api/vcenter/vm")
            finally:
                await self._end(c)
        on = sum(1 for v in vms if v.get("power_state") == "POWERED_ON")
        host_rows = [row(h.get("name") or h.get("host"), h.get("connection_state", ""),
                         badge="연결됨" if h.get("connection_state") == "CONNECTED" else (h.get("connection_state") or "—"),
                         tone="ok" if h.get("connection_state") == "CONNECTED" else "warn") for h in hosts]
        vm_rows = []
        for v in sorted(vms, key=lambda x: (x.get("power_state") != "POWERED_ON", x.get("name") or "")):
            label, tone = POWER.get(v.get("power_state", ""), (v.get("power_state") or "—", ""))
            prm = {"vm": v["vm"]}
            name = v.get("name") or v["vm"]
            if v.get("power_state") == "POWERED_ON":
                actions = [act("reboot", "재시작", params=prm, confirm=f"{name}의 게스트 OS를 재시작합니다 (VMware Tools 필요)."),
                           act("shutdown", "종료", danger=True, params=prm, confirm=f"{name}의 게스트 OS를 정상 종료합니다 (VMware Tools 필요)."),
                           act("stop", "강제 끄기", danger=True, params=prm, confirm=f"{name}의 전원을 바로 끕니다. 저장하지 않은 데이터가 사라질 수 있습니다.")]
            else:
                actions = [act("start", "켜기", params=prm)]
            mem = v.get("memory_size_MiB")
            note = " · ".join(x for x in (f"vCPU {v['cpu_count']}" if v.get("cpu_count") else "",
                                          f"메모리 {round(mem / 1024, 1)}GB" if mem else "") if x)
            vm_rows.append(row(name, note, badge=label, tone=tone, actions=actions))
        return card(
            summary=f"호스트 {len(hosts)}대 · VM {len(vms)}개",
            metrics=[metric("호스트", len(hosts)), metric("VM", len(vms)), metric("켜진 VM", f"{on} / {len(vms)}"),
                     metric("꺼진 VM", len(vms) - on)],
            sections=[section("호스트", host_rows, empty="호스트가 없습니다"), section("가상 머신", vm_rows, empty="VM이 없습니다")],
        )

    async def action(self, action: str, params: dict):
        vm = str(params.get("vm", ""))
        if not SAFE_VM.match(vm):
            raise ConnectorError("작업 대상이 올바르지 않습니다")
        if action in ("start", "stop", "reset"):
            path, query = f"/api/vcenter/vm/{vm}/power", action
        elif action in ("shutdown", "reboot"):
            path, query = f"/api/vcenter/vm/{vm}/guest/power", action
        else:
            return await super().action(action, params)
        async with self._client() as c:
            await self._session(c)
            try:
                r = await c.post(self.cfg["url"] + path, params={"action": query})
                if r.status_code == 400 and action in ("shutdown", "reboot"):
                    raise ConnectorError("게스트 종료/재시작에는 VMware Tools가 실행 중이어야 합니다")
                r.raise_for_status()
            finally:
                await self._end(c)
        return {"start": "켜기", "stop": "강제 끄기", "reset": "리셋", "shutdown": "종료", "reboot": "재시작"}[action] + "를 요청했습니다"
