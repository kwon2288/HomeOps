"""설정 로드: config.yaml(연결 정보)과 환경 변수(관리자 계정, 비밀 키)."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class MakerApi(BaseModel):
    app_id: int
    token: str


class HubLogin(BaseModel):
    username: str
    password: str


class HubitatCfg(BaseModel):
    id: str
    name: str
    url: str
    role: str = ""
    maker_api: MakerApi | None = None
    login: HubLogin | None = None


class HomeAssistantCfg(BaseModel):
    url: str
    token: str
    verify_ssl: bool = True


class HomebridgeCfg(BaseModel):
    url: str
    username: str = ""
    password: str = ""
    verify_ssl: bool = True


class SynologyCfg(BaseModel):
    url: str
    username: str
    password: str
    verify_ssl: bool = True


class ProxmoxCfg(BaseModel):
    url: str
    token_id: str  # 예: homeops@pve!dashboard
    token_secret: str
    verify_ssl: bool = True
    backup_storage: str = "local"


class PortainerCfg(BaseModel):
    url: str
    api_key: str
    verify_ssl: bool = True


class AlertsCfg(BaseModel):
    battery_warn: int = 30


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


def config_path() -> Path:
    return Path(os.environ.get("HOMEOPS_CONFIG", "config/config.yaml"))


def load_settings() -> Settings:
    path = config_path()
    if not path.exists():
        return Settings()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Settings(**data)


class Runtime(BaseModel):
    admin_user: str
    admin_password: str
    secret_key: str
    cookie_secure: bool
    db_path: Path
    backup_dir: Path
    backup_keep: int


def load_runtime() -> Runtime:
    password = os.environ.get("HOMEOPS_ADMIN_PASSWORD", "")
    secret = os.environ.get("HOMEOPS_SECRET_KEY", "")
    if not password or not secret:
        raise RuntimeError(
            "HOMEOPS_ADMIN_PASSWORD 와 HOMEOPS_SECRET_KEY 환경 변수를 설정해야 합니다 (.env 참고)."
        )
    data_dir = Path(os.environ.get("HOMEOPS_DATA", "data"))
    return Runtime(
        admin_user=os.environ.get("HOMEOPS_ADMIN_USER", "admin"),
        admin_password=password,
        secret_key=secret,
        cookie_secure=os.environ.get("HOMEOPS_COOKIE_SECURE", "true").lower() == "true",
        db_path=data_dir / "homeops.db",
        backup_dir=data_dir / "backups",
        backup_keep=int(os.environ.get("HOMEOPS_BACKUP_KEEP", "10")),
    )
