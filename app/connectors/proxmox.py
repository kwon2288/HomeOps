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
            node_list = []
            for n in nodes:
                node = {
                    "name": n.get("node"), "status": n.get("status"),
                    "cpu_pct": round(n["cpu"] * 100, 1) if n.get("cpu") is not None and n.get("maxmem") else None,
                    "mem_pct": round((n.get("mem") or 0) / n["maxmem"] * 100, 1) if n.get("maxmem") else None,
                    "disk_pct": round((n.get("disk") or 0) / n["maxdisk"] * 100, 1) if n.get("maxdisk") else None,
                    "uptime": n.get("uptime"), "needs_audit": False,
                }
                # 토큰에 Sys.Audit 권한이 없으면 /nodes 가 CPU · 메모리 · 디스크 값을 빼고 준다 → 노드 상세로 한 번 더
                if node["mem_pct"] is None and node["status"] == "online" and SAFE_NODE.match(node["name"] or ""):
                    try:
                        d = self._data(await c.get(f"{self.base}/nodes/{node['name']}/status")) or {}
                        mem, root = d.get("memory") or {}, d.get("rootfs") or {}
                        if d.get("cpu") is not None:
                            node["cpu_pct"] = round(d["cpu"] * 100, 1)
                        if mem.get("total"):
                            node["mem_pct"] = round(mem.get("used", 0) / mem["total"] * 100, 1)
                        if root.get("total"):
                            node["disk_pct"] = round(root.get("used", 0) / root["total"] * 100, 1)
                        node["uptime"] = node["uptime"] or d.get("uptime")
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code in (401, 403):
                            node["needs_audit"] = True
                    except (httpx.HTTPError, ValueError, TypeError, ZeroDivisionError):
                        pass
                    if node["mem_pct"] is None:
                        node["needs_audit"] = True
                node_list.append(node)
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
