"""설정 모델과 실행 환경.

연결 정보는 웹 화면(연결 설정)에서 입력하고 SQLite에 저장한다 (store.py).
아래 HubitatCfg 등은 각 시스템의 API 클라이언트(app/connectors)가 쓰는 형식이다.
환경 변수는 모두 선택 사항이다.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator


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


class FtpCfg(BaseModel):
    enabled: bool = False
    host: str = ""
    port: int = Field(21, ge=1, le=65535)
    tls: bool = False  # FTPS (명시적 TLS)
    username: str = ""
    password: str = ""
    path: str = "/homeops"

    @model_validator(mode="after")
    def _need_host(self):
        if self.enabled and not self.host.strip():
            raise ValueError("FTP 서버 주소를 입력하세요")
        return self


class WebDavCfg(BaseModel):
    enabled: bool = False
    url: str = ""  # 백업을 넣을 폴더 주소, 예: https://nas:5006/homeops/
    username: str = ""
    password: str = ""
    verify_ssl: bool = True

    @model_validator(mode="after")
    def _need_url(self):
        if self.enabled and not self.url.startswith(("http://", "https://")):
            raise ValueError("WebDAV 주소는 http:// 또는 https:// 로 시작해야 합니다")
        return self


class BackupCfg(BaseModel):
    password: str = ""  # 백업 파일 암호 (비어 있으면 백업 불가)
    schedule_enabled: bool = False
    schedule_time: str = Field("03:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = "Asia/Seoul"
    keep_local: int = Field(14, ge=1, le=365)
    keep_remote: int = Field(30, ge=1, le=365)
    include_hub_backups: bool = False
    ftp: FtpCfg = Field(default_factory=FtpCfg)
    webdav: WebDavCfg = Field(default_factory=WebDavCfg)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("시간대 이름이 올바르지 않습니다 (예: Asia/Seoul)") from exc
        return v


class ConnectionCfg(BaseModel):
    """연결 하나. config 의 내용은 연동 플러그인(app/integrations)의 fields 선언을 따른다."""
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,30}$")
    type: str
    name: str = Field(min_length=1, max_length=40)
    config: dict = Field(default_factory=dict)


class Settings(BaseModel):
    connections: list[ConnectionCfg] = Field(default_factory=list)
    alerts: AlertsCfg = Field(default_factory=AlertsCfg)
    backup: BackupCfg = Field(default_factory=BackupCfg)

    def conn(self, conn_id: str) -> ConnectionCfg | None:
        return next((c for c in self.connections if c.id == conn_id), None)


# 설정 화면에서 섹션 단위로 저장하는 일반 설정
SECTION_MODELS: dict[str, type[BaseModel]] = {
    "alerts": AlertsCfg,
    "backup": BackupCfg,
}


class Runtime(BaseModel):
    secret_key: str
    secret_from_env: bool = False
    cookie_secure: bool | None  # None = HTTPS로 접속했을 때만 Secure 쿠키
    db_path: Path
    backup_dir: Path
    backup_keep: int
    app_backup_dir: Path | None = None  # HomeOps 자체 백업 (기본: data/homeops-backups)
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
        app_backup_dir=data_dir / "homeops-backups",
        secret_from_env=bool(os.environ.get("HOMEOPS_SECRET_KEY")),
        admin_user=os.environ.get("HOMEOPS_ADMIN_USER") or None,
        admin_password=os.environ.get("HOMEOPS_ADMIN_PASSWORD") or None,
    )


def app_backup_dir(rt: Runtime) -> Path:
    return rt.app_backup_dir or rt.db_path.parent / "homeops-backups"
