"""Portainer API (Access Token, X-API-Key)."""
from __future__ import annotations

import re
from typing import Any

import httpx

from ..config import PortainerCfg
from .base import ConnectorError, make_client

CONTAINER_ACTIONS = {"start", "stop", "restart"}
STACK_ACTIONS = {"start", "stop"}
SAFE_CID = re.compile(r"^[a-f0-9]{12,64}$")


def strip_docker_log(raw: bytes) -> str:
    """Docker 로그 스트림의 8바이트 프레임 헤더를 걷어낸다 (TTY가 아닌 컨테이너)."""
    out = bytearray()
    i = 0
    if len(raw) >= 8 and raw[0] in (0, 1, 2) and raw[1:4] == b"\x00\x00\x00":
        while i + 8 <= len(raw):
            size = int.from_bytes(raw[i + 4:i + 8], "big")
            out += raw[i + 8:i + 8 + size]
            i += 8 + size
        return out.decode("utf-8", "replace")
    return raw.decode("utf-8", "replace")


class Portainer:
    def __init__(self, cfg: PortainerCfg):
        self.cfg = cfg
        self.base = cfg.url.rstrip("/") + "/api"
        self.headers = {"X-API-Key": cfg.api_key}

    def _client(self) -> httpx.AsyncClient:
        return make_client(verify=self.cfg.verify_ssl, headers=self.headers)

    async def status(self) -> dict[str, Any]:
        async with self._client() as c:
            r = await c.get(f"{self.base}/status")
            r.raise_for_status()
            version = r.json().get("Version")
            r = await c.get(f"{self.base}/endpoints")
            r.raise_for_status()
            endpoints = r.json()
            containers = []
            for ep in endpoints:
                try:
                    cr = await c.get(f"{self.base}/endpoints/{ep['Id']}/docker/containers/json", params={"all": 1})
                    cr.raise_for_status()
                except httpx.HTTPError:
                    continue
                for ct in cr.json():
                    containers.append({
                        "endpoint": ep["Id"],
                        "endpoint_name": ep.get("Name"),
                        "id": ct["Id"],
                        "name": (ct.get("Names") or ["/?"])[0].lstrip("/"),
                        "image": ct.get("Image"),
                        "state": ct.get("State"),
                        "status": ct.get("Status"),
                        "stack": (ct.get("Labels") or {}).get("com.docker.compose.project"),
                    })
            try:
                sr = await c.get(f"{self.base}/stacks")
                sr.raise_for_status()
                stacks = [{
                    "id": s["Id"], "name": s.get("Name"), "endpoint": s.get("EndpointId"),
                    "active": s.get("Status") == 1,
                } for s in sr.json()]
            except httpx.HTTPError:
                stacks = []
        containers.sort(key=lambda x: (x["state"] == "running", x["name"]))
        return {
            "online": True,
            "version": version,
            "containers": containers,
            "stacks": stacks,
            "running": sum(1 for x in containers if x["state"] == "running"),
            "stopped": sum(1 for x in containers if x["state"] != "running"),
        }

    async def container_action(self, endpoint: int, cid: str, action: str) -> None:
        if action not in CONTAINER_ACTIONS or not SAFE_CID.match(cid):
            raise ConnectorError("잘못된 컨테이너 작업")
        async with self._client() as c:
            r = await c.post(f"{self.base}/endpoints/{endpoint}/docker/containers/{cid}/{action}")
            if r.status_code != 304:  # 이미 그 상태
                r.raise_for_status()

    async def container_logs(self, endpoint: int, cid: str, tail: int = 200) -> str:
        if not SAFE_CID.match(cid):
            raise ConnectorError("잘못된 컨테이너 ID")
        async with self._client() as c:
            r = await c.get(
                f"{self.base}/endpoints/{endpoint}/docker/containers/{cid}/logs",
                params={"stdout": 1, "stderr": 1, "tail": min(max(tail, 10), 2000), "timestamps": 1},
            )
            r.raise_for_status()
        return strip_docker_log(r.content)

    async def stack_action(self, stack_id: int, endpoint: int, action: str) -> None:
        if action not in STACK_ACTIONS:
            raise ConnectorError("잘못된 스택 작업")
        async with self._client() as c:
            r = await c.post(f"{self.base}/stacks/{stack_id}/{action}", params={"endpointId": endpoint})
            r.raise_for_status()
