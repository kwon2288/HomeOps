"""HomeOps 백업 파일(.hob) 만들기·열기.

파일 구조: MAGIC + salt(16바이트) + Fernet 토큰
Fernet 안에는 tar.gz 가 들어 있다:
  manifest.json   앱 버전, 만든 시각, 포함 항목
  homeops.db      SQLite 스냅샷 (계정, 연결 설정, 수동 등록, 작업 기록)
  secret.key      연결 설정 비밀값을 푸는 키
  hubitat/*.lzf   (선택) Hubitat 허브 백업 파일
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sqlite3
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

MAGIC = b"HOMEOPS-BACKUP-1\n"
NAME_RE = re.compile(r"^homeops-[0-9]{8}-[0-9]{6}(-[a-z0-9\-]{1,30})?\.hob$")
HUB_FILE_RE = re.compile(r"^[\w\-]+\.lzf$")
REQUIRED_TABLES = {"manual_devices", "platforms", "integration_paths", "audit_log", "kv"}


class BackupError(Exception):
    """화면에 그대로 보여 줄 수 있는 백업·복구 오류."""


@dataclass
class Opened:
    manifest: dict
    db: bytes
    secret_key: str
    hub_files: dict[str, bytes] = field(default_factory=dict)


def backup_name(tag: str = "") -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"homeops-{stamp}{'-' + tag if tag else ''}.hob"


def _fernet(password: str, salt: bytes) -> Fernet:
    key = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return Fernet(base64.urlsafe_b64encode(key))


def _sqlite_snapshot(db_path: Path) -> bytes:
    """사용 중인 DB를 일관된 상태로 복사한다 (SQLite backup API)."""
    with tempfile.TemporaryDirectory() as tmp:
        dst_path = Path(tmp) / "snap.db"
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(dst_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return dst_path.read_bytes()


def _add(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = int(datetime.now().timestamp())
    info.mode = 0o600
    tar.addfile(info, io.BytesIO(data))


def create(db_path: Path, secret_key: str, password: str, version: str,
           hub_files: list[Path] | None = None) -> bytes:
    if not password:
        raise BackupError("백업 암호를 먼저 설정하세요")
    hub_files = hub_files or []
    manifest = {
        "app": "HomeOps",
        "version": version,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hub_files": [p.name for p in hub_files],
    }
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        _add(tar, "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode())
        _add(tar, "homeops.db", _sqlite_snapshot(db_path))
        _add(tar, "secret.key", secret_key.encode())
        for p in hub_files:
            _add(tar, f"hubitat/{p.name}", p.read_bytes())
    salt = os.urandom(16)
    return MAGIC + salt + _fernet(password, salt).encrypt(buf.getvalue())


def open_backup(data: bytes, password: str) -> Opened:
    if not data.startswith(MAGIC):
        raise BackupError("HomeOps 백업 파일이 아닙니다")
    if not password:
        raise BackupError("백업 암호가 필요합니다")
    salt = data[len(MAGIC):len(MAGIC) + 16]
    try:
        raw = _fernet(password, salt).decrypt(data[len(MAGIC) + 16:])
    except InvalidToken as exc:
        raise BackupError("백업 암호가 맞지 않거나 파일이 손상되었습니다") from exc

    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        for m in tar.getmembers():
            if not m.isfile() or m.size > 2 * 1024**3:
                continue
            name = m.name
            ok = name in ("manifest.json", "homeops.db", "secret.key") or (
                name.startswith("hubitat/") and HUB_FILE_RE.match(name.split("/", 1)[1]) and name.count("/") == 1
            )
            if ok:
                f = tar.extractfile(m)
                files[name] = f.read() if f else b""
    for need in ("manifest.json", "homeops.db", "secret.key"):
        if need not in files:
            raise BackupError(f"백업 파일에 {need} 가 없습니다")
    manifest = json.loads(files["manifest.json"])
    if manifest.get("app") != "HomeOps":
        raise BackupError("HomeOps 백업 파일이 아닙니다")
    _check_db(files["homeops.db"])
    return Opened(
        manifest=manifest,
        db=files["homeops.db"],
        secret_key=files["secret.key"].decode().strip(),
        hub_files={k.split("/", 1)[1]: v for k, v in files.items() if k.startswith("hubitat/")},
    )


def _check_db(data: bytes) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "check.db"
        p.write_bytes(data)
        conn = sqlite3.connect(p)
        try:
            ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        except sqlite3.DatabaseError as exc:
            raise BackupError("백업 안의 DB를 읽을 수 없습니다") from exc
        finally:
            conn.close()
    if ok != "ok":
        raise BackupError("백업 안의 DB가 손상되었습니다")
    if not REQUIRED_TABLES <= tables:
        raise BackupError("백업 안의 DB 구조가 HomeOps와 맞지 않습니다")
