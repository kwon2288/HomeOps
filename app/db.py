"""SQLite 저장소: 수동 등록 기기, 플랫폼 역할, 연동 경로, 작업 기록."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

SCHEMA = """
CREATE TABLE IF NOT EXISTS manual_devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT '',
    roles TEXT NOT NULL DEFAULT '[]',
    memo TEXT NOT NULL DEFAULT '',
    sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS platforms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    use TEXT NOT NULL DEFAULT '',
    features TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS integration_paths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    src TEXT NOT NULL,
    via TEXT NOT NULL DEFAULT '',
    dst TEXT NOT NULL,
    check_ref TEXT NOT NULL DEFAULT '',
    sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    result TEXT NOT NULL
);
"""

TABLES = {
    "manual_devices": ["name", "model", "platform", "ip", "roles", "memo", "sort"],
    "platforms": ["name", "use", "features", "path", "sort"],
    "integration_paths": ["src", "via", "dst", "check_ref", "sort"],
}

SEED_DEFAULT = Path(__file__).with_name("seed_default.yaml")


class Database:
    def __init__(self, path: Path, seed_path: Path | None = None):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)
        self._seed(seed_path or SEED_DEFAULT)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _seed(self, seed_path: Path) -> None:
        if not seed_path.exists():
            return
        data = yaml.safe_load(seed_path.read_text(encoding="utf-8")) or {}
        for table in TABLES:
            if self.list(table):
                continue
            for i, row in enumerate(data.get(table, [])):
                row = dict(row)
                row.setdefault("sort", i)
                self.create(table, row)

    @staticmethod
    def _decode(table: str, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        if table == "manual_devices":
            d["roles"] = json.loads(d.get("roles") or "[]")
        return d

    def _encode(self, table: str, data: dict[str, Any]) -> dict[str, Any]:
        cols = TABLES[table]
        out = {k: v for k, v in data.items() if k in cols}
        if table == "manual_devices" and "roles" in out:
            out["roles"] = json.dumps(list(out["roles"]), ensure_ascii=False)
        return out

    def list(self, table: str) -> list[dict[str, Any]]:
        assert table in TABLES
        with self._conn() as c:
            rows = c.execute(f"SELECT * FROM {table} ORDER BY sort, id").fetchall()
        return [self._decode(table, r) for r in rows]

    def get(self, table: str, row_id: int) -> dict[str, Any] | None:
        assert table in TABLES
        with self._conn() as c:
            r = c.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
        return self._decode(table, r) if r else None

    def create(self, table: str, data: dict[str, Any]) -> dict[str, Any]:
        values = self._encode(table, data)
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        with self._lock, self._conn() as c:
            cur = c.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(values.values()))
            new_id = cur.lastrowid
        return self.get(table, new_id)  # type: ignore[arg-type]

    def update(self, table: str, row_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        values = self._encode(table, data)
        if values:
            sets = ", ".join(f"{k} = ?" for k in values)
            with self._lock, self._conn() as c:
                c.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*values.values(), row_id))
        return self.get(table, row_id)

    def delete(self, table: str, row_id: int) -> bool:
        assert table in TABLES
        with self._lock, self._conn() as c:
            cur = c.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
        return cur.rowcount > 0

    def audit(self, action: str, target: str, result: str) -> None:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO audit_log (ts, action, target, result) VALUES (?, ?, ?, ?)",
                (ts, action, target, result[:500]),
            )

    def audit_list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
