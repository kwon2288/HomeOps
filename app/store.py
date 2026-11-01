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

from .config import Settings
from .db import Database

MASK = "__SET__"

# 섹션별 비밀값 필드 (점으로 하위 객체 지정)
SECRET_FIELDS: dict[str, list[str]] = {
    "home_assistant": ["token"],
    "homebridge": ["password"],
    "synology": ["password"],
    "proxmox": ["token_secret"],
    "portainer": ["api_key"],
    "backup": ["password", "ftp.password", "webdav.password"],
}
# Hubitat 허브마다 들어 있는 비밀값
HUB_SECRETS = ["maker_api.token", "login.password"]


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
        if v:
            _set(item, path, fn(v))


def _map_section(section: str, data: Any, fn: Callable[[str], str]) -> Any:
    if data is None:
        return None
    data = copy.deepcopy(data)
    if section == "hubitat":
        for hub in data:
            _map_paths(hub, HUB_SECRETS, fn)
    else:
        _map_paths(data, SECRET_FIELDS.get(section, []), fn)
    return data


def map_secrets(settings: dict[str, Any], fn: Callable[[str], str]) -> dict[str, Any]:
    return {k: _map_section(k, v, fn) for k, v in settings.items()}


def masked(settings: Settings) -> dict[str, Any]:
    """화면용: 비밀값은 MASK 로 바꾼다."""
    return map_secrets(settings.model_dump(), lambda _v: MASK)


def _keep(item: Any, previous: Any, paths: list[str]) -> None:
    for path in paths:
        if _get(item, path.rsplit(".", 1)[0]) is None and "." in path:
            continue  # 하위 객체가 없으면 건너뜀 (예: 허브 로그인 안 씀)
        value, prev = _get(item, path), _get(previous, path)
        if value in (None, "", MASK):
            _set(item, path, prev if prev else "")


def merge_section(section: str, new: Any, old: Any) -> Any:
    """화면에서 받은 섹션 값에서 MASK/빈 비밀값을 기존 값으로 채운다."""
    if new is None:
        return None
    new = copy.deepcopy(new)
    if section == "hubitat":
        old_by_id = {h["id"]: h for h in (old or [])}
        for hub in new:
            prev = old_by_id.get(hub.get("orig_id") or hub.get("id"), {})
            hub.pop("orig_id", None)
            _keep(hub, prev, HUB_SECRETS)
    else:
        _keep(new, old or {}, SECRET_FIELDS.get(section, []))
    return new


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
        return Settings(**map_secrets(json.loads(raw), self._dec))

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
