"""Portainer (Access Token)."""
from __future__ import annotations

from ..config import PortainerCfg
from ..connectors.base import ConnectorError
from ..connectors.portainer import Portainer as Client
from .base import Integration, act, card, field, metric, row, section, url_field, verify_field


class PortainerIntegration(Integration):
    type = "portainer"
    title = "Portainer"
    category = "infra"
    desc = "컨테이너 · 스택 · 로그"
    order = 30
    help = "Portainer → My account → <b>Access tokens</b>에서 만든 토큰입니다."
    fields = [
        url_field("https://192.168.0.x:9443"),
        field("api_key", "Access Token", secret=True, required=True, full=True),
        verify_field(default=False),
    ]

    def _client(self) -> Client:
        return Client(PortainerCfg(url=self.cfg["url"], api_key=self.cfg.get("api_key") or "",
                                   verify_ssl=self.cfg.get("verify_ssl", False)))

    def confirm_required(self, action: str) -> bool:
        return action in {"restart", "stop", "stack-stop"}

    async def status(self) -> dict:
        p = await self._client().status()
        rows = []
        for c in p["containers"]:
            prm = {"endpoint": c["endpoint"], "id": c["id"]}
            on = c["state"] == "running"
            actions = ([act("restart", "재시작", params=prm, confirm=f"{c['name']} 컨테이너를 재시작합니다."),
                        act("stop", "중지", danger=True, params=prm, confirm=f"{c['name']} 컨테이너를 중지합니다.")]
                       if on else [act("start", "시작", params=prm)])
            rows.append(row(c["name"], f"{c['image']} · {c['status']}" + (f" · 스택 {c['stack']}" if c.get("stack") else ""),
                            actions=actions + [act("logs", "로그", params=prm)]))
        stacks = [row(s["name"], f"엔드포인트 {s['endpoint']}", badge="실행 중" if s["active"] else "중지",
                      tone="ok" if s["active"] else "",
                      actions=[act("stack-stop", "중지", danger=True, params={"stack": s["id"], "endpoint": s["endpoint"]},
                                   confirm=f"{s['name']} 스택의 모든 컨테이너가 멈춥니다.")] if s["active"]
                      else [act("stack-start", "시작", params={"stack": s["id"], "endpoint": s["endpoint"]})])
                  for s in p["stacks"]]
        return card(
            summary=f"Portainer {p['version']}",
            metrics=[metric("실행 중", p["running"]), metric("중지됨", p["stopped"]),
                     metric("스택", len(p["stacks"])), metric("전체 컨테이너", len(p["containers"]))],
            sections=[section("컨테이너 (중지된 것 먼저)", rows, empty="컨테이너가 없습니다")]
            + ([section("스택", stacks)] if stacks else []),
        )

    async def action(self, action: str, params: dict):
        c = self._client()
        try:
            if action in ("start", "restart", "stop", "logs"):
                endpoint, cid = int(params["endpoint"]), str(params["id"])
                if action == "logs":
                    return {"text": await c.container_logs(endpoint, cid, 300), "title": "컨테이너 로그 (최근 300줄)"}
                await c.container_action(endpoint, cid, action)
                return {"start": "시작", "restart": "재시작", "stop": "중지"}[action] + "했습니다"
            if action in ("stack-start", "stack-stop"):
                await c.stack_action(int(params["stack"]), int(params["endpoint"]), action.split("-")[1])
                return "스택을 " + ("시작" if action == "stack-start" else "중지") + "했습니다"
        except (KeyError, TypeError, ValueError) as exc:
            raise ConnectorError("작업 대상이 올바르지 않습니다") from exc
        return await super().action(action, params)
