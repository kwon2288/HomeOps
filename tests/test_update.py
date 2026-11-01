import io
import tarfile

import httpx
import pytest
import respx

from app import VERSION, update

RAW = "https://raw.githubusercontent.com/kwon2288/HomeOps/main"
TARBALL = "https://codeload.github.com/kwon2288/HomeOps/tar.gz/refs/heads/main"

README = f"""# HomeOps
## 변경 이력

### v99.1.0 — 2099-01-02
- **큰 기능** 추가
  - 세부 항목 `code`
- 고친 것

### v99.0.0 — 2099-01-01
- 첫 새 버전

### v{VERSION} — 2026-11-01
- 지금 버전 (안 보여야 함)

## 라이선스
"""


def mock_github(version="99.1.0"):
    respx.get(f"{RAW}/app/__init__.py").mock(return_value=httpx.Response(200, text=f'VERSION = "{version}"\n'))
    respx.get(f"{RAW}/README.md").mock(return_value=httpx.Response(200, text=README))


def tarball(version: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        def add(name, text, mode=0o644):
            data = text.encode()
            info = tarfile.TarInfo(f"HomeOps-main/{name}")
            info.size, info.mode = len(data), mode
            tar.addfile(info, io.BytesIO(data))
        add("app/__init__.py", f'VERSION = "{version}"\n')
        add("app/main.py", "# main\n")
        add("install.sh", "#!/bin/sh\n", 0o755)
        evil = tarfile.TarInfo("HomeOps-main/../../evil.txt")
        evil.size = 1
        tar.addfile(evil, io.BytesIO(b"x"))
    return buf.getvalue()


def test_changelog_and_versions():
    items = update.changelog(README, VERSION)
    assert [c["version"] for c in items] == ["99.1.0", "99.0.0"]
    assert items[0]["date"] == "2099-01-02"
    assert items[0]["items"][1] == {"text": "세부 항목 `code`", "sub": True}
    assert update.vtuple("0.10.0") > update.vtuple("0.9.9")
    assert update.read_version('"""doc"""\nVERSION = "1.2.3"\n') == "1.2.3"


@respx.mock
def test_check_status(client, monkeypatch):
    monkeypatch.delenv("HOMEOPS_INSTALL", raising=False)
    monkeypatch.setattr(update, "LEGACY_UPDATER", update.Path("/nonexistent"))
    mock_github()
    st = client.get("/api/update").json()
    assert st["current"] == VERSION and st["latest"] == "99.1.0" and st["available"]
    assert [c["version"] for c in st["changelog"]] == ["99.1.0", "99.0.0"]
    assert st["mode"] == "manual" and st["can_update"] is False and st["hint"]
    # 직접 실행 중이면 업데이트 거부
    assert client.post("/api/update/apply", json={"confirm": True}).status_code == 400
    # 캐시: 두 번째 조회는 GitHub에 다시 묻지 않음
    calls = respx.calls.call_count
    client.get("/api/update")
    assert respx.calls.call_count == calls


@respx.mock
def test_check_failure_keeps_last_known(client):
    mock_github()
    client.get("/api/update")
    respx.get(f"{RAW}/app/__init__.py").mock(side_effect=httpx.ConnectError("down"))
    st = client.get("/api/update?refresh=1").json()
    assert st["latest"] == "99.1.0" and "GitHub에 연결하지 못했습니다" in st["error"]


@respx.mock
def test_lxc_apply_writes_request(client, monkeypatch, tmp_path):
    monkeypatch.setenv("HOMEOPS_INSTALL", "lxc")
    unit = tmp_path / "homeops-update.path"
    monkeypatch.setattr(update, "HELPER_UNIT", unit)
    mock_github()
    st = client.get("/api/update").json()
    assert st["mode"] == "lxc" and not st["can_update"]   # 아직 helper 설치 전 (예전 install.sh)
    unit.write_text("")
    assert client.post("/api/update/apply", json={}).status_code == 400            # confirm 필요
    # 백업 암호를 정해 두면 시작 전에 자동 백업
    client.put("/api/settings/backup", json={"password": "pw1234"})
    r = client.post("/api/update/apply", json={"confirm": True})
    assert r.status_code == 200, r.text
    assert r.json()["backup"].endswith("-before-update.hob")
    req = tmp_path / "update" / "request"
    assert req.read_text().strip() == "update"
    assert client.get("/api/update").json()["job"]["state"] == "queued"
    assert client.post("/api/update/apply", json={"confirm": True}).status_code == 409

    # root helper 가 처리한 뒤의 상태
    req.unlink()
    (tmp_path / "update" / "state").write_text("failed\n")
    (tmp_path / "update" / "update.log").write_text("git pull 실패\n")
    job = client.get("/api/update").json()["job"]
    assert job["state"] == "failed" and "git pull" in job["log"]


@respx.mock
def test_docker_apply_downloads_code(client, monkeypatch, tmp_path):
    monkeypatch.setenv("HOMEOPS_INSTALL", "docker")
    restarted = []
    monkeypatch.setattr(update, "_restart", lambda: restarted.append(True))
    mock_github()
    respx.get(TARBALL).mock(return_value=httpx.Response(200, content=tarball("99.1.0")))
    (tmp_path / "code" / "app").mkdir(parents=True)          # 예전에 받아 둔 코드
    r = client.post("/api/update/apply", json={"confirm": True})
    assert r.status_code == 200, r.text
    code = tmp_path / "code"
    assert update.read_version((code / "app" / "__init__.py").read_text()) == "99.1.0"
    assert (code / "install.sh").stat().st_mode & 0o111
    assert (tmp_path / "code.prev").exists() and not (tmp_path / "evil.txt").exists()
    assert not list(tmp_path.parent.glob("evil.txt"))
    assert restarted == [True]
    assert client.get("/api/update").json()["job"]["state"] == "restarting"


@respx.mock
def test_docker_apply_rejects_bad_download(client, monkeypatch, tmp_path):
    monkeypatch.setenv("HOMEOPS_INSTALL", "docker")
    monkeypatch.setattr(update, "_restart", lambda: pytest.fail("다시 시작하면 안 됨"))
    update._docker_job.clear()
    mock_github()
    respx.get(TARBALL).mock(return_value=httpx.Response(200, content=tarball(VERSION)))  # 새 버전이 아님
    assert client.post("/api/update/apply", json={"confirm": True}).status_code == 200
    job = client.get("/api/update").json()["job"]
    assert job["state"] == "failed" and "새롭지 않습니다" in job["log"]
    assert not (tmp_path / "code").exists()
