"""웹에서 입력한 연결 정보와 관리자 계정을 DB에 보관한다.

- 토큰·비밀번호 같은 비밀값은 Fernet으로 암호화해 저장한다 (키: data/secret.key).
- 화면으로 내려보낼 때는 비밀값 대신 MASK 를 보낸다. 화면에서 MASK나 빈 값을 다시 보내면 기존 값을 유지한다.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import secrets
from typing import Any, Callable

from cryptography.fernet import Fernet, InvalidToken

from . import integrations
from .config import Settings
from .db import Database

MASK = "__SET__"

# 섹션별 비밀값 (점으로 하위 객체 지정)
SECTION_SECRETS: dict[str, list[str]] = {
    "backup": ["password", "ftp.password", "webdav.password"],
}
# v0.5 이하 설정 형식의 비밀값 (자동 이전할 때만 사용)
LEGACY_SECRETS: dict[str, list[str]] = {
    "home_assistant": ["token"], "homebridge": ["password"], "synology": ["password"],
    "proxmox": ["token_secret"], "portainer": ["api_key"],
}
LEGACY_HUB_SECRETS = ["maker_api.token", "login.password"]


def _get(obj: Any, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def _set(obj: Any, path: str, value: Any) -> None:
    *parents, last = path.split(".")
    for part in parents:
        if not isinstance(obj, dict) or not isinstance(obj.get(part), dict):
            return
        obj = obj[part]
    if isinstance(obj, dict):
        obj[last] = value


def _map_paths(item: Any, paths: list[str], fn: Callable[[str], str]) -> None:
    for path in paths:
        v = _get(item, path)
        if v and isinstance(v, str):
            _set(item, path, fn(v))


def conn_secret_paths(type_: str) -> list[str]:
    cls = integrations.get(type_)
    return [f"config.{n}" for n in cls.secret_fields()] if cls else []


def map_secrets(settings: dict[str, Any], fn: Callable[[str], str]) -> dict[str, Any]:
    data = copy.deepcopy(settings)
    for conn in data.get("connections") or []:
        _map_paths(conn, conn_secret_paths(conn.get("type", "")), fn)
    for section, paths in SECTION_SECRETS.items():
        if isinstance(data.get(section), dict):
            _map_paths(data[section], paths, fn)
    # 예전 형식 (이전용)
    for section, paths in LEGACY_SECRETS.items():
        if isinstance(data.get(section), dict):
            _map_paths(data[section], paths, fn)
    for hub in data.get("hubitat") or []:
        _map_paths(hub, LEGACY_HUB_SECRETS, fn)
    return data


def masked(settings: Settings) -> dict[str, Any]:
    """화면용: 비밀값은 MASK 로 바꾼다."""
    return map_secrets(settings.model_dump(), lambda _v: MASK)


def masked_conn(conn: dict) -> dict:
    conn = copy.deepcopy(conn)
    _map_paths(conn, conn_secret_paths(conn.get("type", "")), lambda _v: MASK)
    return conn


def _keep(item: Any, previous: Any, paths: list[str]) -> None:
    for path in paths:
        value, prev = _get(item, path), _get(previous, path)
        if value in (None, "", MASK):
            _set(item, path, prev if prev else "")


def merge_conn(new: dict, old: dict | None) -> dict:
    """화면에서 받은 연결 값에서 MASK/빈 비밀값을 기존 값으로 채운다."""
    new = copy.deepcopy(new)
    new.setdefault("config", {})
    _keep(new, old or {}, conn_secret_paths(new.get("type", "")))
    return new


def merge_section(section: str, new: Any, old: Any) -> Any:
    if new is None:
        return None
    new = copy.deepcopy(new)
    _keep(new, old or {}, SECTION_SECRETS.get(section, []))
    return new


def migrate_legacy(data: dict) -> dict:
    """v0.5 이하의 시스템별 설정을 연결 목록(connections)으로 옮긴다. 비밀값은 풀린 상태로 받는다."""
    if "connections" in data:
        return data
    conns: list[dict] = []
    for h in data.get("hubitat") or []:
        maker, login = h.get("maker_api") or {}, h.get("login") or {}
        conns.append({"id": h["id"], "type": "hubitat", "name": h.get("name") or h["id"], "config": {
            "url": h.get("url", ""), "role": h.get("role", ""),
            "app_id": maker.get("app_id"), "token": maker.get("token", ""),
            "login_user": login.get("username", ""), "login_password": login.get("password", ""),
        }})
    simple = {
        "home_assistant": ("home-assistant", "Home Assistant"), "homebridge": ("homebridge", "Homebridge"),
        "synology": ("nas", "Synology NAS"), "proxmox": ("proxmox", "Proxmox VE"), "portainer": ("portainer", "Portainer"),
    }
    for key, (cid, name) in simple.items():
        if data.get(key):
            conns.append({"id": cid, "type": key, "name": name, "config": dict(data[key])})
    out = {k: v for k, v in data.items() if k not in ("hubitat", *simple)}
    out["connections"] = conns
    return out


class SettingsStore:
    def __init__(self, db: Database, secret_key: str):
        self.db = db
        key = base64.urlsafe_b64encode(hashlib.sha256(("homeops-settings:" + secret_key).encode()).digest())
        self._fernet = Fernet(key)

    def _enc(self, value: str) -> str:
        return "enc:" + self._fernet.encrypt(value.encode()).decode()

    def _dec(self, value: str) -> str:
        if not value.startswith("enc:"):
            return value
        try:
            return self._fernet.decrypt(value[4:].encode()).decode()
        except InvalidToken:
            return ""  # 비밀 키가 바뀐 경우: 다시 입력해야 함

    def load(self) -> Settings:
        raw = self.db.kv_get("settings")
        if not raw:
            return Settings()
        data = map_secrets(json.loads(raw), self._dec)
        if "connections" not in data:  # 예전 형식이면 새 형식으로 옮기고 저장
            settings = Settings(**migrate_legacy(data))
            self.save(settings)
            return settings
        return Settings(**data)

    def save(self, settings: Settings) -> None:
        data = map_secrets(settings.model_dump(), self._enc)
        self.db.kv_set("settings", json.dumps(data, ensure_ascii=False))

    # ---- 관리자 계정 ----

    def admin(self) -> dict[str, str] | None:
        raw = self.db.kv_get("admin")
        return json.loads(raw) if raw else None

    def set_admin(self, username: str, password: str) -> None:
        salt = secrets.token_bytes(16)
        digest = _hash(password, salt)
        self.db.kv_set("admin", json.dumps({
            "user": username, "salt": salt.hex(), "hash": digest.hex(),
        }))

    def check_admin(self, username: str, password: str) -> bool:
        a = self.admin()
        if not a:
            return False
        digest = _hash(password, bytes.fromhex(a["salt"]))
        ok_user = hmac.compare_digest(username.encode(), a["user"].encode())
        ok_pass = hmac.compare_digest(digest, bytes.fromhex(a["hash"]))
        return ok_user and ok_pass


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
