"""설정 모델(연결 정보)과 실행 환경.

연결 정보는 웹 화면(연결 설정)에서 입력하고 SQLite에 저장한다 (store.py).
환경 변수는 모두 선택 사항이다.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from pydantic import BaseModel, Field


class MakerApi(BaseModel):
    app_id: int
    token: str = ""


class HubLogin(BaseModel):
    username: str
    password: str = ""


class HubitatCfg(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,30}$")
    name: str = Field(min_length=1, max_length=40)
    url: str = Field(pattern=r"^https?://")
    role: str = Field("", max_length=40)
    maker_api: MakerApi | None = None
    login: HubLogin | None = None


class HomeAssistantCfg(BaseModel):
    url: str = Field(pattern=r"^https?://")
    token: str = ""
    verify_ssl: bool = True


class HomebridgeCfg(BaseModel):
    url: str = Field(pattern=r"^https?://")
    username: str = ""
    password: str = ""
    verify_ssl: bool = True


class SynologyCfg(BaseModel):
    url: str = Field(pattern=r"^https?://")
    username: str
    password: str = ""
    verify_ssl: bool = True


class ProxmoxCfg(BaseModel):
    url: str = Field(pattern=r"^https?://")
    token_id: str  # 예: homeops@pve!dashboard
    token_secret: str = ""
    verify_ssl: bool = True
    backup_storage: str = "local"


class PortainerCfg(BaseModel):
    url: str = Field(pattern=r"^https?://")
    api_key: str = ""
    verify_ssl: bool = True


class AlertsCfg(BaseModel):
    battery_warn: int = Field(30, ge=1, le=100)


class Settings(BaseModel):
    hubitat: list[HubitatCfg] = Field(default_factory=list)
    home_assistant: HomeAssistantCfg | None = None
    homebridge: HomebridgeCfg | None = None
    synology: SynologyCfg | None = None
    proxmox: ProxmoxCfg | None = None
    portainer: PortainerCfg | None = None
    alerts: AlertsCfg = Field(default_factory=AlertsCfg)

    def hub(self, hub_id: str) -> HubitatCfg | None:
        return next((h for h in self.hubitat if h.id == hub_id), None)


# 설정 화면에서 섹션 단위로 저장할 때 쓰는 모델
SECTION_MODELS: dict[str, type[BaseModel]] = {
    "home_assistant": HomeAssistantCfg,
    "homebridge": HomebridgeCfg,
    "synology": SynologyCfg,
    "proxmox": ProxmoxCfg,
    "portainer": PortainerCfg,
    "alerts": AlertsCfg,
}


class Runtime(BaseModel):
    secret_key: str
    cookie_secure: bool | None  # None = HTTPS로 접속했을 때만 Secure 쿠키
    db_path: Path
    backup_dir: Path
    backup_keep: int
    # 환경 변수로 관리자 계정을 고정하고 싶을 때만 (보통은 웹에서 만든 계정 사용)
    admin_user: str | None = None
    admin_password: str | None = None


def _secret_key(data_dir: Path) -> str:
    env = os.environ.get("HOMEOPS_SECRET_KEY")
    if env:
        return env
    path = data_dir / "secret.key"
    if path.exists():
        return path.read_text().strip()
    data_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(48)
    path.write_text(key)
    path.chmod(0o600)
    return key


def load_runtime() -> Runtime:
    data_dir = Path(os.environ.get("HOMEOPS_DATA", "data"))
    secure = os.environ.get("HOMEOPS_COOKIE_SECURE", "auto").lower()
    return Runtime(
        secret_key=_secret_key(data_dir),
        cookie_secure=None if secure == "auto" else secure == "true",
        db_path=data_dir / "homeops.db",
        backup_dir=data_dir / "backups",
        backup_keep=int(os.environ.get("HOMEOPS_BACKUP_KEEP", "10")),
        admin_user=os.environ.get("HOMEOPS_ADMIN_USER") or None,
        admin_password=os.environ.get("HOMEOPS_ADMIN_PASSWORD") or None,
    )
