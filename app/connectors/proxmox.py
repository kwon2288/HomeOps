"""Proxmox VE API (API 토큰 인증)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import httpx

from ..config import ProxmoxCfg
from .base import ConnectorError, make_client

POWER_ACTIONS = {"start", "shutdown", "reboot", "stop"}
SAFE_NODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,62}$")


class Proxmox:
    def __init__(self, cfg: ProxmoxCfg):
        self.cfg = cfg
        self.base = cfg.url.rstrip("/") + "/api2/json"
        self.headers = {"Authorization": f"PVEAPIToken={cfg.token_id}={cfg.token_secret}"}

    def _client(self) -> httpx.AsyncClient:
        return make_client(verify=self.cfg.verify_ssl, headers=self.headers)

    @staticmethod
    def _data(r: httpx.Response) -> Any:
        r.raise_for_status()
        return r.json().get("data")

    @staticmethod
    def _check_guest(node: str, kind: str, vmid: int) -> None:
        if not SAFE_NODE.match(node) or kind not in ("qemu", "lxc") or not (100 <= vmid <= 999_999_999):
            raise ConnectorError("잘못된 노드 또는 게스트")

    async def status(self) -> dict[str, Any]:
        async with self._client() as c:
            version = self._data(await c.get(f"{self.base}/version")) or {}
            nodes = self._data(await c.get(f"{self.base}/nodes")) or []
            guests = self._data(await c.get(f"{self.base}/cluster/resources", params={"type": "vm"})) or []
        node_list = [{
            "name": n.get("node"),
            "status": n.get("status"),
            "cpu_pct": round((n.get("cpu") or 0) * 100, 1),
            "mem_pct": round((n.get("mem") or 0) / n["maxmem"] * 100, 1) if n.get("maxmem") else None,
            "disk_pct": round((n.get("disk") or 0) / n["maxdisk"] * 100, 1) if n.get("maxdisk") else None,
            "uptime": n.get("uptime"),
        } for n in nodes]
        guest_list = sorted([{
            "node": g.get("node"),
            "type": g.get("type"),
            "vmid": g.get("vmid"),
            "name": g.get("name") or str(g.get("vmid")),
            "status": g.get("status"),
            "cpu_pct": round((g.get("cpu") or 0) * 100, 1),
            "mem_pct": round((g.get("mem") or 0) / g["maxmem"] * 100, 1) if g.get("maxmem") else None,
            "template": bool(g.get("template")),
        } for g in guests if not g.get("template")], key=lambda g: (g["status"] != "running", g["vmid"] or 0))
        return {
            "online": True,
            "version": version.get("version"),
            "nodes": node_list,
            "guests": guest_list,
            "running": sum(1 for g in guest_list if g["status"] == "running"),
        }

    async def power(self, node: str, kind: str, vmid: int, action: str) -> str:
        self._check_guest(node, kind, vmid)
        if action not in POWER_ACTIONS:
            raise ConnectorError("지원하지 않는 작업")
        async with self._client() as c:
            return self._data(await c.post(f"{self.base}/nodes/{node}/{kind}/{vmid}/status/{action}"))

    async def snapshot(self, node: str, kind: str, vmid: int) -> str:
        self._check_guest(node, kind, vmid)
        name = "homeops-" + datetime.now().strftime("%Y%m%d-%H%M")
        async with self._client() as c:
            return self._data(await c.post(
                f"{self.base}/nodes/{node}/{kind}/{vmid}/snapshot",
                data={"snapname": name, "description": "HomeOps에서 생성"},
            ))

    async def backup(self, node: str, vmid: int) -> str:
        self._check_guest(node, "qemu", vmid)
        async with self._client() as c:
            return self._data(await c.post(f"{self.base}/nodes/{node}/vzdump", data={
                "vmid": str(vmid), "storage": self.cfg.backup_storage, "mode": "snapshot", "compress": "zstd",
            }))
