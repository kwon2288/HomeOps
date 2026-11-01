"""원격 백업 저장소: FTP(FTPS) · WebDAV.

목록·삭제는 HomeOps 백업 파일 이름(homeops-*.hob)만 다룬다.
"""
from __future__ import annotations

import asyncio
import ftplib
import io
import ssl
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import unquote, urljoin, urlparse

import httpx

from ..config import FtpCfg, WebDavCfg
from .archive import NAME_RE, BackupError


def _entry(name: str, size: int | None, mtime: float | None) -> dict:
    return {"name": name, "size": size, "mtime": int(mtime) if mtime else None}


# ---------------- FTP ----------------

class FtpTarget:
    label = "FTP"

    def __init__(self, cfg: FtpCfg):
        self.cfg = cfg

    def _connect(self) -> ftplib.FTP:
        if self.cfg.tls:
            ftp: ftplib.FTP = ftplib.FTP_TLS(context=ssl.create_default_context(), timeout=20)
        else:
            ftp = ftplib.FTP(timeout=20)
        try:
            ftp.connect(self.cfg.host.strip(), self.cfg.port)
            ftp.login(self.cfg.username or "anonymous", self.cfg.password or "")
            if isinstance(ftp, ftplib.FTP_TLS):
                ftp.prot_p()
            self._cd(ftp, self.cfg.path or "/")
        except ftplib.error_perm as exc:
            ftp.close()
            msg = str(exc)
            if msg.startswith("530"):
                raise BackupError("FTP 로그인 실패 (아이디·비밀번호 확인)") from exc
            raise BackupError(f"FTP 오류: {msg}") from exc
        except (OSError, EOFError) as exc:
            ftp.close()
            raise BackupError(f"FTP 서버에 연결할 수 없습니다 ({exc.__class__.__name__})") from exc
        return ftp

    @staticmethod
    def _cd(ftp: ftplib.FTP, path: str) -> None:
        """폴더로 이동한다. 없으면 만든다."""
        if path.startswith("/"):
            ftp.cwd("/")
        for part in [p for p in path.split("/") if p]:
            try:
                ftp.cwd(part)
            except ftplib.error_perm:
                ftp.mkd(part)
                ftp.cwd(part)

    def _list(self, ftp: ftplib.FTP) -> list[dict]:
        out = []
        try:
            for name, facts in ftp.mlsd(facts=["size", "modify", "type"]):
                if facts.get("type", "file") == "file" and NAME_RE.match(name):
                    mtime = None
                    if facts.get("modify"):
                        mtime = datetime.strptime(facts["modify"][:14], "%Y%m%d%H%M%S").timestamp()
                    out.append(_entry(name, int(facts.get("size", 0)), mtime))
        except ftplib.error_perm:  # MLSD를 지원하지 않는 서버
            for name in ftp.nlst():
                name = name.rsplit("/", 1)[-1]
                if NAME_RE.match(name):
                    try:
                        size = ftp.size(name)
                    except ftplib.error_perm:
                        size = None
                    out.append(_entry(name, size, None))
        return sorted(out, key=lambda e: e["name"], reverse=True)

    def _run(self, fn):
        def job():
            ftp = self._connect()
            try:
                return fn(ftp)
            finally:
                try:
                    ftp.quit()
                except (ftplib.Error, OSError, EOFError):
                    ftp.close()
        return asyncio.to_thread(job)

    async def test(self) -> str:
        files = await self._run(self._list)
        return f"연결됨 · {self.cfg.path or '/'} 폴더 · 백업 {len(files)}개"

    async def list(self) -> list[dict]:
        return await self._run(self._list)

    async def upload(self, name: str, data: bytes) -> None:
        await self._run(lambda ftp: ftp.storbinary(f"STOR {name}", io.BytesIO(data)))

    async def download(self, name: str) -> bytes:
        def get(ftp):
            buf = io.BytesIO()
            ftp.retrbinary(f"RETR {name}", buf.write)
            return buf.getvalue()
        return await self._run(get)

    async def delete(self, name: str) -> None:
        await self._run(lambda ftp: ftp.delete(name))


# ---------------- WebDAV ----------------

DAV = "{DAV:}"
PROPFIND_BODY = b"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:"><d:prop><d:getcontentlength/><d:getlastmodified/><d:resourcetype/></d:prop></d:propfind>"""


class WebDavTarget:
    label = "WebDAV"

    def __init__(self, cfg: WebDavCfg):
        self.cfg = cfg
        self.base = cfg.url if cfg.url.endswith("/") else cfg.url + "/"

    def _client(self) -> httpx.AsyncClient:
        auth = (self.cfg.username, self.cfg.password) if self.cfg.username else None
        return httpx.AsyncClient(auth=auth, verify=self.cfg.verify_ssl, timeout=httpx.Timeout(20, read=300),
                                 follow_redirects=True)

    @staticmethod
    def _check(r: httpx.Response, what: str) -> None:
        if r.status_code in (401, 403):
            raise BackupError("WebDAV 인증 실패 (아이디·비밀번호 확인)")
        if r.status_code >= 400:
            raise BackupError(f"WebDAV {what} 실패 (HTTP {r.status_code})")

    async def _ensure_folder(self, c: httpx.AsyncClient) -> None:
        r = await c.request("PROPFIND", self.base, headers={"Depth": "0"})
        if r.status_code == 404:
            r = await c.request("MKCOL", self.base)
            self._check(r, "폴더 만들기")
        else:
            self._check(r, "폴더 확인")

    async def _list(self, c: httpx.AsyncClient) -> list[dict]:
        r = await c.request("PROPFIND", self.base, headers={"Depth": "1", "Content-Type": "application/xml"},
                            content=PROPFIND_BODY)
        self._check(r, "목록 조회")
        out = []
        root = ET.fromstring(r.content)
        for resp in root.iter(f"{DAV}response"):
            href = resp.findtext(f"{DAV}href") or ""
            name = unquote(urlparse(href).path.rstrip("/").rsplit("/", 1)[-1])
            if not NAME_RE.match(name):
                continue
            size = resp.findtext(f".//{DAV}getcontentlength")
            modified = resp.findtext(f".//{DAV}getlastmodified")
            mtime = None
            if modified:
                try:
                    mtime = parsedate_to_datetime(modified).timestamp()
                except (TypeError, ValueError):
                    pass
            out.append(_entry(name, int(size) if size and size.isdigit() else None, mtime))
        return sorted(out, key=lambda e: e["name"], reverse=True)

    async def test(self) -> str:
        try:
            async with self._client() as c:
                await self._ensure_folder(c)
                files = await self._list(c)
        except httpx.HTTPError as exc:
            raise BackupError(f"WebDAV 서버에 연결할 수 없습니다 ({exc.__class__.__name__})") from exc
        return f"연결됨 · 백업 {len(files)}개"

    async def list(self) -> list[dict]:
        try:
            async with self._client() as c:
                return await self._list(c)
        except httpx.HTTPError as exc:
            raise BackupError(f"WebDAV 서버에 연결할 수 없습니다 ({exc.__class__.__name__})") from exc

    async def upload(self, name: str, data: bytes) -> None:
        try:
            async with self._client() as c:
                await self._ensure_folder(c)
                r = await c.put(urljoin(self.base, name), content=data,
                                headers={"Content-Type": "application/octet-stream"})
                self._check(r, "업로드")
        except httpx.HTTPError as exc:
            raise BackupError(f"WebDAV 업로드 실패 ({exc.__class__.__name__})") from exc

    async def download(self, name: str) -> bytes:
        try:
            async with self._client() as c:
                r = await c.get(urljoin(self.base, name))
                self._check(r, "다운로드")
                return r.content
        except httpx.HTTPError as exc:
            raise BackupError(f"WebDAV 다운로드 실패 ({exc.__class__.__name__})") from exc

    async def delete(self, name: str) -> None:
        try:
            async with self._client() as c:
                r = await c.delete(urljoin(self.base, name))
                if r.status_code != 404:
                    self._check(r, "삭제")
        except httpx.HTTPError as exc:
            raise BackupError(f"WebDAV 삭제 실패 ({exc.__class__.__name__})") from exc


def targets(cfg_backup, only_enabled: bool = True) -> dict[str, FtpTarget | WebDavTarget]:
    out: dict[str, FtpTarget | WebDavTarget] = {}
    if cfg_backup.ftp.enabled or not only_enabled:
        out["ftp"] = FtpTarget(cfg_backup.ftp)
    if cfg_backup.webdav.enabled or not only_enabled:
        out["webdav"] = WebDavTarget(cfg_backup.webdav)
    return out
