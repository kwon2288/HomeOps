"""Proxmox VE (API 토큰)."""
from __future__ import annotations

from ..config import ProxmoxCfg
from ..connectors.base import ConnectorError
from ..connectors.proxmox import Proxmox as Client
from .base import Integration, act, card, field, metric, row, section, uptime, url_field, verify_field


class ProxmoxVE(Integration):
    type = "proxmox"
    title = "Proxmox VE"
    category = "infra"
    desc = "VM · LXC 전원 · 스냅샷 · 백업"
    order = 20
    help = ("Datacenter → Permissions → <b>API Tokens</b>에서 만든 토큰입니다. 토큰 ID는 <code>사용자@realm!토큰이름</code> 형식이에요. "
            "권장 권한: VM.Audit, VM.PowerMgmt, VM.Snapshot, VM.Backup, Datastore.Audit, Datastore.AllocateSpace, Sys.Audit")
    fields = [
        url_field("https://192.168.0.x:8006"),
        field("token_id", "토큰 ID", required=True, ph="homeops@pve!dashboard"),
        field("token_secret", "토큰 Secret", secret=True, required=True),
        field("backup_storage", "백업 저장소", default="local", ph="local"),
        verify_field(default=False),
    ]

    def _client(self) -> Client:
        return Client(ProxmoxCfg(url=self.cfg["url"], token_id=self.cfg.get("token_id") or "",
                                 token_secret=self.cfg.get("token_secret") or "",
                                 verify_ssl=self.cfg.get("verify_ssl", False),
                                 backup_storage=self.cfg.get("backup_storage") or "local"))

    async def status(self) -> dict:
        p = await self._client().status()
        node = (p["nodes"] or [{}])[0]
        rows = []
        for g in p["guests"]:
            on = g["status"] == "running"
            prm = {"node": g["node"], "kind": g["type"], "vmid": g["vmid"]}
            label = f"{g['name']}({g['vmid']})"
            power = ([act("reboot", "재시작", params=prm, confirm=f"{label}에 재시작 신호를 보냅니다."),
                      act("shutdown", "종료", danger=True, params=prm, confirm=f"{label}을(를) 정상 종료합니다.")]
                     if on else [act("start", "시작", params=prm)])
            rows.append(row(
                g["name"],
                f"{'LXC' if g['type'] == 'lxc' else 'VM'} {g['vmid']} · {g['node']} · "
                + (f"CPU {round(g['cpu_pct'])}% · 메모리 {round(g['mem_pct'] or 0)}%" if on else "중지됨"),
                actions=power + [act("snapshot", "스냅샷", params=prm), act("backup", "백업", params=prm)],
            ))
        return card(
            summary=" · ".join(x for x in (node.get("name"), f"PVE {p['version']}",
                                           f"가동 {uptime(node.get('uptime'))}" if node.get("uptime") else "") if x),
            metrics=[
                metric("노드 CPU", node.get("cpu_pct"), node.get("cpu_pct"), "%"),
                metric("노드 메모리", node.get("mem_pct"), node.get("mem_pct"), "%"),
                metric("루트 디스크", node.get("disk_pct"), node.get("disk_pct"), "%"),
                metric("실행 중 VM/LXC", f"{p['running']} / {len(p['guests'])}"),
            ],
            sections=[section("VM · LXC", rows, empty="게스트가 없습니다")],
        )

    async def action(self, action: str, params: dict):
        try:
            node, kind, vmid = str(params["node"]), str(params["kind"]), int(params["vmid"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ConnectorError("작업 대상이 올바르지 않습니다") from exc
        c = self._client()
        if action in ("start", "reboot", "shutdown"):
            await c.power(node, kind, vmid, action)
            return {"start": "시작", "reboot": "재시작", "shutdown": "종료"}[action] + "을 요청했습니다"
        if action == "snapshot":
            await c.snapshot(node, kind, vmid)
            return "스냅샷을 요청했습니다"
        if action == "backup":
            await c.backup(node, vmid)
            return "백업 작업을 시작했습니다"
        return await super().action(action, params)
