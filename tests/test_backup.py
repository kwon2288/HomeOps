import socket
import threading
import time
from urllib.parse import quote

import pytest

from app.backup.archive import MAGIC
from app.config import Runtime, Settings
from app.store import MASK

from .conftest import make_client

BACKUP_PW = "백업암호-1234"


def _setup_backup(c, **extra):
    body = {"password": BACKUP_PW, "keep_local": 14, **extra}
    r = c.put("/api/settings/backup", json=body)
    assert r.status_code == 200, r.text
    return r.json()["backup"]


def test_backup_requires_password(client):
    r = client.post("/api/backup/run", json={})
    assert r.status_code == 400 and "백업 암호" in r.json()["detail"]


def test_backup_and_restore_local(runtime):
    c = make_client(Settings(proxmox={"url": "https://pve.test", "token_id": "a@pve!b", "token_secret": "pve-secret"}), runtime)
    assert _setup_backup(c)["password"] == MASK
    c.post("/api/registry/devices", json={"name": "Apple TV 4K", "platform": "HomeKit", "roles": ["HomeKit 홈 허브"]})

    r = c.post("/api/backup/run", json={})
    assert r.status_code == 200, r.text
    name = r.json()["name"]
    local = c.get("/api/backup").json()["local"]
    assert [e["name"] for e in local] == [name]

    raw = c.get(f"/api/backup/local/{name}").content
    assert raw.startswith(MAGIC)
    assert b"pve-secret" not in raw and "Apple TV".encode() not in raw  # 암호화됨

    # 데이터를 바꾼 뒤 복구
    dev = next(d for d in c.get("/api/registry/devices").json() if d["name"] == "Apple TV 4K")
    c.delete(f"/api/registry/devices/{dev['id']}")
    assert c.post("/api/backup/restore", json={"source": "local", "name": name}).status_code == 400  # 확인 필요
    bad = c.post("/api/backup/restore", json={"source": "local", "name": name, "password": "wrong", "confirm": True})
    assert bad.status_code == 400 and "암호" in bad.json()["detail"]

    r = c.post("/api/backup/restore", json={"source": "local", "name": name, "confirm": True})
    assert r.status_code == 200, r.text
    assert r.json()["safety_backup"].endswith("-before-restore.hob")
    names = [d["name"] for d in c.get("/api/registry/devices").json()]
    assert "Apple TV 4K" in names
    assert c.app.state.ctx.settings.proxmox.token_secret == "pve-secret"
    assert any(a["action"] == "HomeOps 복구" for a in c.get("/api/audit").json())
    assert c.get("/api/backup").json()["last"]["name"] == name  # 백업 기록은 복구 후에도 유지


def test_restore_into_new_install(tmp_path):
    """다른 설치(다른 비밀 키)에 업로드로 복구해도 토큰을 풀 수 있어야 한다."""
    rt1 = Runtime(secret_key="test-secret", cookie_secure=None, db_path=tmp_path / "old" / "homeops.db",
                  backup_dir=tmp_path / "old" / "backups", backup_keep=2)
    c1 = make_client(Settings(portainer={"url": "https://ptn.test", "api_key": "ptn-key"}), rt1, login=False)
    c1.post("/api/auth/setup", json={"username": "min", "password": "oldpassword1"})
    _setup_backup(c1)
    name = c1.post("/api/backup/run", json={}).json()["name"]
    data = c1.get(f"/api/backup/local/{name}").content

    rt2 = Runtime(secret_key="other-key", cookie_secure=None, db_path=tmp_path / "new" / "homeops.db",
                  backup_dir=tmp_path / "new" / "backups", backup_keep=2)
    c2 = make_client(Settings(), rt2, login=False)
    c2.post("/api/auth/setup", json={"username": "admin", "password": "newinstall1"})
    r = c2.post("/api/backup/restore-upload", content=data,
                headers={"X-Confirm": "yes", "X-Backup-Password": quote(BACKUP_PW)})
    assert r.status_code == 200, r.text
    ctx2 = c2.app.state.ctx
    assert ctx2.settings.portainer.api_key == "ptn-key"
    assert (tmp_path / "new" / "secret.key").read_text() == "test-secret"
    # 비밀 키가 바뀌었으므로 기존 세션은 끊기고, 백업 당시 계정으로 로그인
    assert c2.get("/api/backup").status_code == 401
    assert c2.post("/api/auth/login", json={"username": "min", "password": "oldpassword1"}).status_code == 200


def test_prune_local(runtime):
    c = make_client(Settings(), runtime)
    _setup_backup(c, keep_local=2)
    names = []
    for _ in range(3):
        names.append(c.post("/api/backup/run", json={}).json()["name"])
        time.sleep(1.05)  # 파일 이름이 초 단위
    local = [e["name"] for e in c.get("/api/backup").json()["local"]]
    assert local == sorted(names, reverse=True)[:2]


def test_bad_upload(client):
    r = client.post("/api/backup/restore-upload", content=b"not a backup", headers={"X-Confirm": "yes"})
    assert r.status_code == 400


# ---- 실제 FTP 서버로 확인 ----

def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def ftp_server(tmp_path):
    pytest.importorskip("pyftpdlib")
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer

    root = tmp_path / "ftp"
    root.mkdir()
    auth = DummyAuthorizer()
    auth.add_user("bk", "ftp-pass", str(root), perm="elradfmwMT")
    handler = type("H", (FTPHandler,), {"authorizer": auth})
    port = _free_port()
    server = FTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=server.serve_forever, kwargs={"timeout": 0.2}, daemon=True)
    t.start()
    yield port, root
    server.close_all()


def test_ftp_upload_list_restore(runtime, ftp_server):
    port, root = ftp_server
    c = make_client(Settings(), runtime)
    ftp = {"enabled": True, "host": "127.0.0.1", "port": port, "username": "bk", "password": "ftp-pass", "path": "/homeops/nightly"}

    bad = c.post("/api/backup/test/ftp", json={"ftp": {**ftp, "password": "nope"}}).json()
    assert bad["ok"] is False and "로그인" in bad["message"]
    ok = c.post("/api/backup/test/ftp", json={"ftp": ftp}).json()
    assert ok["ok"], ok

    _setup_backup(c, ftp=ftp, keep_remote=1)
    r = c.post("/api/backup/run", json={}).json()
    assert r["uploads"] == {"ftp": "성공"}
    assert (root / "homeops" / "nightly" / r["name"]).exists()

    remote = c.get("/api/backup/remote/ftp").json()
    assert [e["name"] for e in remote] == [r["name"]]

    time.sleep(1.05)
    r2 = c.post("/api/backup/run", json={}).json()
    remote = [e["name"] for e in c.get("/api/backup/remote/ftp").json()]
    assert remote == [r2["name"]]  # keep_remote=1 로 정리됨

    res = c.post("/api/backup/restore", json={"source": "ftp", "name": r2["name"], "confirm": True})
    assert res.status_code == 200, res.text


# ---- 실제 WebDAV 서버로 확인 ----

@pytest.fixture
def webdav_server(tmp_path):
    pytest.importorskip("wsgidav")
    from cheroot import wsgi
    from wsgidav.wsgidav_app import WsgiDAVApp

    root = tmp_path / "dav"
    root.mkdir()
    app = WsgiDAVApp({
        "provider_mapping": {"/": str(root)},
        "simple_dc": {"user_mapping": {"*": {"bk": {"password": "dav-pass"}}}},
        "http_authenticator": {"accept_basic": True, "accept_digest": False, "default_to_digest": False},
        "verbose": 0, "logging": {"enable": False},
    })
    port = _free_port()
    server = wsgi.Server(("127.0.0.1", port), app)
    t = threading.Thread(target=server.start, daemon=True)
    t.start()
    for _ in range(50):
        if server.ready:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", root
    server.stop()


def test_webdav_upload_list_restore(runtime, webdav_server, monkeypatch):
    for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(k, raising=False)
    base, root = webdav_server
    c = make_client(Settings(), runtime)
    dav = {"enabled": True, "url": f"{base}/backups/homeops", "username": "bk", "password": "dav-pass"}

    bad = c.post("/api/backup/test/webdav", json={"webdav": {**dav, "password": "nope"}}).json()
    assert bad["ok"] is False and "인증" in bad["message"]
    assert c.post("/api/backup/test/webdav", json={"webdav": dav}).json()["ok"] is False  # 상위 폴더 없음

    (root / "backups").mkdir()
    ok = c.post("/api/backup/test/webdav", json={"webdav": dav}).json()
    assert ok["ok"], ok
    assert (root / "backups" / "homeops").is_dir()  # 폴더 자동 생성

    _setup_backup(c, webdav=dav)
    r = c.post("/api/backup/run", json={}).json()
    assert r["uploads"] == {"webdav": "성공"}, r
    remote = c.get("/api/backup/remote/webdav").json()
    assert [e["name"] for e in remote] == [r["name"]] and remote[0]["size"] == r["size"]

    res = c.post("/api/backup/restore", json={"source": "webdav", "name": r["name"], "confirm": True})
    assert res.status_code == 200, res.text
