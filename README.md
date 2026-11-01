# HomeOps

홈랩 인프라와 스마트홈 허브를 한 화면에서 보고 관리하는 웹앱입니다.
설치 후에는 **계정 만들기부터 모든 연결 설정까지 웹 화면에서** 합니다. 설정 파일을 직접 고칠 일이 없습니다.

| 메뉴 | 대상 | 할 수 있는 일 |
|---|---|---|
| **인프라** | Synology NAS · Proxmox VE · Portainer · UniFi Network · VMware vCenter · 웹 상태 확인 | 볼륨·디스크·CPU·메모리 확인, NAS 재부팅 / VM·LXC 시작·종료·재시작·스냅샷·백업 / 컨테이너 시작·중지·재시작·로그, 스택 시작·중지 / UniFi 장치 상태·재시작 / vCenter 호스트·VM 전원 |
| **스마트홈 허브** | Hubitat · Home Assistant · Homebridge + 수동 등록 기기 | 허브 상태·펌웨어·메모리·온도, 허브 백업(파일 보관)·재부팅, HA 백업·재시작, Homebridge 재시작 / API가 없는 기기(Apple TV, HomePod, Nest Hub, Aqara 허브 등)를 역할과 함께 등록하고 ping으로 응답 확인 / 플랫폼별 용도·기능·연결 경로 정리 |
| **스마트홈 연동** | 플랫폼 간 연동 경로 · 기기 | 연동 경로별 상태, 방별 기기 목록과 켜기/끄기, 배터리 부족·외출 중 열린 문·허브 무응답 알림 |
| **연결 설정** | 위 모든 시스템 | **+ 연결 추가**로 쓰는 시스템만 골라 연결, 저장 전 **연결 테스트**, 연결별 편집·삭제, 알림 기준, 관리자 비밀번호 변경 |
| **백업 · 복구** | HomeOps 데이터 전체 | 지금 백업 / 매일 자동 백업, 로컬과 **FTP(FTPS) · WebDAV**에 함께 저장, 보관 개수 자동 정리, 로컬·원격 목록이나 업로드한 파일로 복구 |

- 재부팅·종료·중지 같은 위험한 작업은 확인 창을 한 번 더 거치고, 모든 제어·설정 변경은 **작업 기록**에 남습니다.
- 휴대폰에서는 하단 탭 메뉴로 바뀝니다 (홈 화면에 추가해 앱처럼 쓸 수 있음).
- 처음에는 아무것도 없는 상태로 시작합니다. 연결한 시스템만 각 메뉴에 나타나고, 빈 화면에서 바로 "+ 추가"로 연결할 수 있습니다.
- 모든 종류를 **여러 개씩** 연결할 수 있습니다 (예: Proxmox 2대, NAS 2대).
- 연동은 **플러그인 구조**라 새 시스템은 `app/integrations/`에 파일 하나만 추가하면 화면까지 자동으로 붙습니다 ([새 연동 추가하기](#새-연동-추가하기)).
- 토큰·비밀번호는 암호화해서 저장하고, 화면에는 "저장됨"으로만 표시합니다. 바꿀 때만 새로 입력하면 됩니다.

## 설치

두 가지 중 편한 쪽을 고르세요. 기능은 같습니다.

| | A. LXC에 바로 설치 (권장) | B. 기존 Docker 호스트에 올리기 |
|---|---|---|
| 필요한 것 | Debian 12 / Ubuntu 24.04 LXC 하나 | 이미 쓰는 Docker + Portainer |
| Docker | 필요 없음 | 기존 것 사용 |
| 자원 | RAM 약 100MB, 디스크 1GB 미만 | 컨테이너 하나 |
| 업데이트 | **웹 화면에서** (왼쪽 아래 버전 → 지금 업데이트) | **웹 화면에서** (왼쪽 아래 버전 → 지금 업데이트) |

### A. LXC에 바로 설치 (Docker 없이)

1. Proxmox에서 **Debian 12** LXC를 만듭니다 (1 vCPU · 512MB RAM · 4GB 디스크면 충분, 비특권 컨테이너 그대로).
2. LXC 콘솔에서:

```bash
apt update && apt install -y git
git clone https://github.com/kwon2288/HomeOps.git /opt/homeops
/opt/homeops/install.sh
```

> 저장소가 비공개라면 clone 주소에 GitHub 토큰을 넣으세요: `https://<토큰>@github.com/kwon2288/HomeOps.git`

`install.sh`가 하는 일: Python 가상환경과 의존성 설치, `homeops` 서비스 계정 생성, systemd 서비스 등록·시작. 데이터는 `/var/lib/homeops`에 저장되어 코드 업데이트와 상관없이 유지됩니다.

| 할 일 | 명령 |
|---|---|
| 업데이트 | 웹 화면 왼쪽 아래 버전 → **지금 업데이트** (콘솔에서는 `homeops-update`) |
| 상태 · 로그 | `systemctl status homeops` · `journalctl -u homeops -f` |
| 포트 바꾸기 | `HOMEOPS_PORT=9090 /opt/homeops/install.sh` |
| 환경 변수 추가 | `/etc/default/homeops`에 `HOMEOPS_COOKIE_SECURE=true` 같은 줄 추가 후 `systemctl restart homeops` |

### B. 기존 Docker 호스트에 올리기 (Portainer 스택)

1. Portainer → **Stacks → Add stack → Repository**
2. Repository URL `https://github.com/kwon2288/HomeOps`, Reference `refs/heads/main`, Compose path `docker-compose.yml`
   (비공개 저장소면 Authentication을 켜고 GitHub 아이디와 토큰 입력)
3. **Deploy the stack**. 업데이트는 웹 화면에서 합니다 (아래 **업데이트** 참고)

명령줄로 할 때는 `git clone` 후 `docker compose up -d --build`. 데이터는 `homeops-data` 볼륨에 저장됩니다.

### 업데이트

새 버전이 나오면 왼쪽 아래 버전 옆에 **새 버전** 표시가 뜹니다 (1시간마다 GitHub 확인, 업데이트 화면은 열 때마다 확인). 버전을 누르면 바뀌는 점이 보이고, **지금 업데이트**를 누르면 1~2분 뒤 자동으로 새 화면이 열립니다.

- 백업 암호를 정해 두었다면 업데이트 직전에 자동으로 백업합니다 (`…-before-update.hob`). 문제가 생기면 **백업 · 복구**에서 되돌리세요.
- 연결 설정과 데이터는 그대로 유지됩니다.

| 설치 방식 | 웹 업데이트가 하는 일 |
|---|---|
| A. LXC | root로 도는 `homeops-update.path` 서비스가 요청을 받아 `git pull` + `install.sh`를 실행합니다 (HomeOps 자체는 root 권한이 없음). 기록은 `/var/lib/homeops/update/update.log` |
| B. Docker | 새 코드를 데이터 볼륨(`code/`)에 받고 컨테이너를 다시 시작합니다. 컨테이너가 뜰 때 이미지보다 새 버전이면 그 코드로 실행하고, 새 코드가 망가져 있으면 이미지에 들어 있는 버전으로 실행합니다. `restart: unless-stopped`가 있어야 다시 뜹니다 |

> **v0.6.1 이하에서 처음 올라올 때 한 번만** 예전 방식으로 업데이트하세요. A는 LXC 콘솔에서 `homeops-update`, B는 Portainer에서 스택을 **Pull and redeploy** (새 `docker-compose.yml`의 `pull_policy: build` 덕분에 이미지를 새로 빌드합니다). 그다음부터는 웹에서 됩니다.

### 처음 접속

1. `http://<설치한 곳 IP>:8080` 접속 → **관리자 계정 만들기** (처음 한 번만 나오는 화면)
2. **연결 설정** 화면에서 "무엇부터 연결할까요?"에 나오는 시스템 중 쓰는 것만 골라 입력하고 **연결 테스트 → 저장**. 나머지는 나중에 **+ 연결 추가**로 언제든 붙입니다
3. 저장하는 즉시 각 메뉴에 반영됩니다 (재시작 필요 없음)

> 처음 계정 만들기 화면은 계정이 없을 때 누구나 열 수 있습니다. 설치 직후 바로 계정을 만들고, 그 전에는 외부에 열지 마세요.

데이터(계정, 연결 설정, 수동 등록 기기, 작업 기록, 백업 파일)는 A는 `/var/lib/homeops`, B는 `homeops-data` 볼륨에 있습니다. 아래 **백업 · 복구** 기능으로 한 파일로 받아 두거나 다른 HomeOps로 옮길 수 있습니다 (A ↔ B 사이 이동도 가능).

### 외부 접속 (권장: NPM + HTTPS)

이 앱은 허브 재부팅이나 컨테이너 중지까지 할 수 있으므로 **HTTP로 바로 포트포워딩하지 마세요.**

1. Nginx Proxy Manager에 Proxy Host 추가 → `http://<설치한 곳 IP>:8080`, SSL 인증서 발급, Force SSL 켜기
2. 가능하면 Cloudflare Access(또는 국가 제한 + WAF 규칙)를 앞에 한 겹 더 두는 것을 권합니다.

HTTPS로 접속하면 로그인 쿠키가 자동으로 Secure로 설정됩니다. 로그인은 5번 틀리면 해당 IP가 5분간 잠깁니다.

## 삭제

데이터까지 지우기 전에 **백업 · 복구**에서 "지금 백업"으로 백업 파일을 받아 두면, 나중에 다시 설치해도 계정과 연결 설정을 그대로 되살릴 수 있습니다.

### A. LXC에 바로 설치한 경우

HomeOps 전용 LXC라면 Proxmox에서 그 LXC를 삭제하는 것이 가장 깔끔합니다. LXC는 남기고 HomeOps만 지우려면:

```bash
systemctl disable --now homeops
systemctl disable --now homeops-update.path
rm /etc/systemd/system/homeops.service /etc/systemd/system/homeops-update.{path,service} /usr/local/bin/homeops-update /usr/local/bin/homeops-update-web
systemctl daemon-reload
rm -rf /opt/homeops
userdel homeops
```

데이터 폴더(`/var/lib/homeops`)는 위 명령으로는 남아 있어서, 다시 설치하면 그대로 이어서 쓸 수 있습니다. 완전히 지우려면:

```bash
rm -rf /var/lib/homeops
```

### B. Portainer 스택으로 올린 경우

1. Portainer → **Stacks** → homeops 선택 → **Remove**
2. 데이터까지 지우려면 **Volumes**에서 `homeops-data` 삭제

명령줄로 설치했다면 저장소 폴더에서 `docker compose down`(데이터 유지) 또는 `docker compose down -v`(데이터까지 삭제) 후 폴더를 지우면 됩니다.

## 백업과 복구

**백업 · 복구** 메뉴에서 설정합니다.

1. **백업 암호**를 먼저 정합니다. 백업 파일에는 토큰·비밀번호가 들어 있어 파일 전체를 이 암호로 암호화합니다. 암호를 잊으면 복구할 수 없으니 따로 적어 두세요.
2. 필요하면 **+ 저장소 추가**로 **FTP**(FTPS 가능)나 **WebDAV**(Synology WebDAV, Nextcloud 등)를 추가하고 연결 테스트 후 저장합니다. 저장 폴더가 없으면 만듭니다.
3. **지금 백업**을 누르거나 **매일 자동 백업** 시각을 정합니다 (기본 03:30, Asia/Seoul).

| 항목 | 내용 |
|---|---|
| 백업 파일 | `homeops-YYYYMMDD-HHMMSS.hob` — 계정, 연결 설정, 수동 등록 기기, 플랫폼 역할, 연동 경로, 작업 기록, 암호화 키. 선택하면 Hubitat 허브 백업 파일(허브별 최신 1개)도 포함 |
| 암호화 | 백업 암호 → scrypt로 키 생성 → Fernet(AES-128-CBC + HMAC-SHA256) |
| 저장 위치 | 로컬(데이터 폴더의 `homeops-backups/`) + 켜 둔 FTP · WebDAV 전부 (원격 업로드가 실패해도 로컬에는 남고, 화면과 작업 기록에 실패가 표시됨) |
| 보관 개수 | 로컬 기본 14개, 원격 기본 30개. 넘으면 오래된 것부터 지움 (HomeOps 백업 파일만) |
| 복구 | 로컬 · FTP · WebDAV 목록에서 고르거나, PC에 받아 둔 `.hob` 파일을 올려서 복구. 복구 직전 상태는 로컬에 `-before-restore` 백업으로 자동 보관 |

- 다른 LXC로 옮길 때: 새 HomeOps를 설치하고 계정을 만든 뒤, **파일로 복구**에서 백업 파일과 백업 암호를 넣으면 됩니다. 복구 후에는 백업 당시 계정으로 로그인합니다.
- `HOMEOPS_SECRET_KEY` 환경 변수를 쓰고 있다면, 그 값이 백업 당시 키와 다를 때 토큰을 풀 수 없습니다 (복구 화면에 안내가 나옴).

## 연결 정보 준비하기

연결 설정 화면의 각 카드에도 같은 안내가 있습니다.

| 시스템 | 필요한 것 | 만드는 곳 |
|---|---|---|
| Hubitat (허브마다) | 허브 주소, Maker API App ID · Access Token | 허브 웹 → Apps → Add Built-In App → **Maker API** ("Allow Access via Local IP Address" 켜기, 관리할 기기 선택). 예시 URL `/apps/api/<App ID>/...?access_token=<토큰>` |
| Home Assistant | 주소, 장기 액세스 토큰 | HA 프로필 → 보안 → 장기 액세스 토큰 |
| Homebridge | 주소, UI 로그인 계정 | config-ui-x 계정. 액세서리 목록·HB 배지는 insecure 모드(-I) 필요 |
| Synology NAS | 주소, 계정 (전용 계정 권장) | 제어판 → 사용자. 재부팅·스토리지 조회에 관리자 그룹 필요. **2단계 인증을 켠 계정**이면 처음 저장할 때 인증 앱의 6자리 코드를 함께 넣으면 HomeOps가 DSM의 신뢰할 수 있는 기기로 등록되어 이후엔 코드 없이 로그인 (개인 설정 → 보안 → 신뢰할 수 있는 기기에서 해제 가능) |
| Proxmox VE | 주소, 토큰 ID · Secret | Datacenter → Permissions → API Tokens. 권장 권한: VM.Audit, VM.PowerMgmt, VM.Snapshot, VM.Backup, Datastore.Audit, Datastore.AllocateSpace, Sys.Audit |
| Portainer | 주소, Access Token | My account → Access tokens |
| UniFi Network | 콘솔 주소, API 키 | UniFi 콘솔(UDR 등)의 Network 앱 → Settings → Integrations(버전에 따라 Control Plane → Integrations). 주소는 `https://192.168.0.1`처럼 콘솔 주소 그대로 |
| VMware vCenter | 주소, vCenter 계정 | vCenter 7.0 U2 이상. VM 전원 제어에는 가상 머신 → 상호 작용 → 전원 권한 필요. 게스트 종료·재시작은 VMware Tools 필요. ESXi 단독 호스트는 아직 미지원 |
| 웹 상태 확인 | 웹 주소 | 전용 연동이 없는 장비·서비스. 응답 여부와 응답 시간, 웹 화면 바로가기 (로그인 화면 401·403도 "응답"으로 봄) |

### Hubitat 참고

- 기기 목록·제어·모드·HSM은 공식 **Maker API**를 씁니다.
- 메모리·온도·DB 크기·펌웨어·재부팅·백업은 허브 관리 화면이 쓰는 **비공식 URL**(`/hub/advanced/*`, `/hub2/hubData`, `/hub/reboot`, `/hub/backupDB`)이라 펌웨어 업데이트 후 동작이 달라질 수 있습니다. 값이 안 나오면 "—"로 표시되고 나머지 기능은 그대로 동작합니다.
- 허브에 로그인 보안을 켰다면 허브 카드에 허브 로그인 계정도 입력하세요.
- 허브 백업 파일은 데이터 폴더의 `backups/`에 허브별로 10개까지 보관되고, 허브 화면에서 내려받을 수 있습니다.

## 고급: 환경 변수 (모두 선택)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `HOMEOPS_COOKIE_SECURE` | `auto` | `auto`는 HTTPS로 접속할 때만 Secure 쿠키. `true`/`false`로 고정 가능 |
| `HOMEOPS_BACKUP_KEEP` | `10` | Hubitat 백업 파일 보관 개수 (허브별) |
| `HOMEOPS_SECRET_KEY` | 자동 생성 | 지정하지 않으면 데이터 폴더에 `secret.key`를 만들어 씁니다 |
| `HOMEOPS_ADMIN_USER` / `HOMEOPS_ADMIN_PASSWORD` | 없음 | 웹 계정 대신 고정 계정을 쓰고 싶을 때만. 지정하면 웹 계정 만들기·비밀번호 변경이 꺼집니다 |
| `HOMEOPS_REPO` / `HOMEOPS_BRANCH` | `kwon2288/HomeOps` / `main` | 웹 업데이트가 새 버전을 확인할 GitHub 저장소 (포크해서 쓸 때) |
| `HOMEOPS_GITHUB_TOKEN` | 없음 | 저장소가 비공개일 때 새 버전 확인 · 내려받기에 쓸 토큰 |
| `HOMEOPS_SEED` | 없음 | 비어 있는 DB에 수동 등록 기기·플랫폼 역할·연동 경로를 미리 넣을 YAML 파일 (`manual_devices`, `platforms`, `integration_paths` 목록) |

## 개발

```bash
pip install -r requirements-dev.txt
pytest
uvicorn app.main:get_app --factory --reload --port 8080   # http://127.0.0.1:8080
```

```
app/
  main.py            앱 생성, 라우터 연결
  config.py          설정 모델 · 환경 변수
  store.py           연결 설정·관리자 계정 저장 (비밀값 암호화)
  backup/            백업 파일 만들기·열기, FTP·WebDAV, 백업·복구·자동 백업
  auth.py            첫 실행 계정 만들기, 로그인, 비밀번호 변경
  core.py            공통 헬퍼 (상태 감싸기, 작업 기록, ping)
  db.py              SQLite
  integrations/      연동 플러그인 (시스템 하나 = 파일 하나, 자동 등록)
  connectors/        일부 연동이 쓰는 API 클라이언트
  routers/           connections · registry · smarthome · settings · backup
  static/            웹 화면 (index.html, app.css, app.js — 빌드 과정 없음)
tests/               pytest (외부 API는 respx로 흉내, FTP·WebDAV는 실제 서버를 띄워 확인)
```

### 새 연동 추가하기

`app/integrations/`에 파일 하나를 만들고 `Integration`을 상속한 클래스를 두면, 앱을 다시 시작할 때 자동으로 등록됩니다.
"+ 연결 추가" 목록, 입력 폼, 연결 테스트, 상태 카드, 작업 버튼, 비밀값 암호화까지 클래스 선언만 보고 처리합니다.

```python
# app/integrations/mything.py
from ..connectors.base import ConnectorError, make_client
from .base import Integration, act, card, field, metric, row, section, url_field, verify_field


class MyThing(Integration):
    type = "mything"                  # 저장용 고유 이름 (바꾸지 않기)
    title = "My Thing"                # 화면 이름
    category = "infra"                # infra(인프라) | smarthome(스마트홈 허브)
    desc = "목록에 보일 한 줄 설명"
    help = "토큰을 만드는 곳 등 안내 (HTML 가능)"
    fields = [
        url_field("https://192.168.0.x"),
        field("api_key", "API 키", secret=True, required=True),   # secret=True → 암호화 저장, 화면에 가림
        verify_field(default=False),
    ]

    async def status(self) -> dict:
        async with make_client(verify=self.cfg["verify_ssl"], headers={"X-API-Key": self.cfg["api_key"]}) as c:
            data = (await c.get(self.cfg["url"] + "/api/status")).json()
        return card(
            summary=f"버전 {data['version']}",
            metrics=[metric("CPU", data["cpu"], pct=data["cpu"], unit="%")],
            sections=[section("장치", [row(d["name"], d["ip"], badge="온라인", tone="ok",
                                          actions=[act("reboot", "재시작", danger=True, params={"id": d["id"]},
                                                       confirm="이 장치를 재시작합니다.")]) for d in data["devices"]])],
        )

    async def action(self, action, params):
        if action == "reboot":
            ...  # params["id"] 로 재시작 요청
            return "재시작을 요청했습니다"
        raise ConnectorError("지원하지 않는 작업입니다")
```

- `status()`가 예외를 내면 카드에 "오류"와 메시지가 표시되고, 다른 연결은 그대로 보입니다.
- `confirm`을 준 작업과 이름이 reboot·restart·shutdown·stop 인 작업은 서버도 확인을 요구합니다 (`confirm_required()`로 바꿀 수 있음).
- 기기 목록·켜기/끄기를 스마트홈 연동 화면에 보태려면 `provides_devices = True`와 `devices()`, `command()`를 구현합니다 (`hubitat.py` 참고).
- 테스트는 `tests/test_app.py`의 UniFi · vCenter 예처럼 respx로 API 응답을 흉내 내면 됩니다.

### 주요 API

| 경로 | 설명 |
|---|---|
| `GET /api/auth/status` · `POST /api/auth/setup` | 첫 실행 여부 · 관리자 계정 만들기 |
| `GET /api/integrations` | 연동 종류와 입력 칸 선언 (화면이 이걸 보고 폼을 만듦) |
| `GET/POST /api/connections` · `PUT/DELETE /api/connections/{id}` | 연결 목록(비밀값 가림) · 추가 · 수정 · 삭제 |
| `POST /api/connections/test` | 저장하지 않고 연결만 시험 |
| `GET /api/status?category=infra\|smarthome` | 메뉴별 상태 카드 |
| `POST /api/connections/{id}/actions/{action}` | 카드의 작업 버튼 (본문 `{"params": {...}, "confirm": true}`) |
| `GET /api/smarthome` · `POST /api/smarthome/devices/{연결 id}/{기기 id}/{on\|off}` | 연동 경로 · 기기 · 알림 · 기기 켜기/끄기 |
| `GET /api/settings` · `PUT /api/settings/{alerts\|backup}` | 알림 기준 · 백업 설정 |
| `GET/POST/PUT/DELETE /api/registry/{devices\|platforms\|paths}` | 수동 등록 · 플랫폼 역할 · 연동 경로 |
| `GET /api/audit` | 작업 기록 |
| `GET /api/backup` · `POST /api/backup/run` | 백업 상태·목록 · 지금 백업 |
| `GET /api/backup/remote/{ftp\|webdav}` · `POST /api/backup/test/{ftp\|webdav}` | 원격 목록 · 연결 테스트 |
| `POST /api/backup/restore` · `POST /api/backup/restore-upload` | 목록에서 복구 · 파일 올려서 복구 |
| `GET /api/update` · `POST /api/update/apply` | 새 버전 확인(`?refresh=1`로 바로 확인) · 업데이트 시작 |

위험한 작업(재부팅·종료·중지·재시작)은 본문에 `{"confirm": true}`가 있어야 실행됩니다.

## 변경 이력

### v0.7.3 — 2026-11-01
- 업데이트 화면을 열 때마다 GitHub에서 새로 확인 (전에는 6시간 동안 이전 확인 결과를 써서 방금 나온 버전이 안 보였음)
- 브랜치 이름 대신 최신 커밋 기준으로 확인 — GitHub가 최대 5분 묵은 파일을 주는 문제 회피
- 왼쪽 아래 "새 버전" 표시는 1시간마다 확인

### v0.7.2 — 2026-11-01
- **Hubitat 기기 목록이 느린 허브 대응**: Maker API `/devices/all`은 고른 기기 전체의 속성까지 보내서 기기가 많으면 오래 걸림
  - 상태 카드 · 연결 테스트는 가벼운 `/devices`(id · 이름만)로 기기 수를 셈
  - 기기 화면의 전체 목록은 최대 45초까지 기다리고, 그래도 늦으면 마지막으로 받은 목록을 보여 주며 "기기 목록 응답이 느림"으로 알림
- 시간 초과 오류에 **어느 요청이 몇 초 만에 끊겼는지** 표시 (예: `응답 시간 초과 (/apps/api/12/devices/all) — 연결은 됐지만 45초 안에 응답이 오지 않았습니다`). 토큰은 표시하지 않음
- 원인을 짐작하던 문구("장비가 바쁘거나 재시작 중") 삭제

### v0.7.1 — 2026-11-01
- **Hubitat 연결 오류를 원인별로 안내**: 허브에 먼저 짧게(4초) 닿는지 확인하고, 안 되면 "연결을 받지 않음(IP·전원·네트워크 확인)", "연결 거부(주소·포트 확인)", "연결은 됐지만 응답 없음"으로 알려 줌. 전에는 요청을 하나씩 기다리다 "응답 시간 초과"만 떴음
- Hubitat 상태 조회 요청을 한꺼번에 보내서 더 빨라짐
- **허브 로그인 보안을 켠 허브**에서 상태 조회 · 재부팅 · 백업이 오류로 실패하던 문제 수정
- 다른 연동도 시간 초과를 "연결 시간 초과"(장비에 안 닿음)와 "응답 시간 초과"(닿았지만 응답 없음)로 나눠 표시

### v0.7.0 — 2026-11-01
- **웹에서 업데이트**: 왼쪽 아래 버전에 새 버전 표시, 바뀌는 점(이 변경 이력) 보기, **지금 업데이트** 버튼
  - LXC: root로 도는 `homeops-update.path`가 요청을 받아 `git pull` + `install.sh` 실행. 진행 기록을 화면에서 볼 수 있음
  - Docker: 새 코드를 데이터 볼륨에 받고 자동으로 다시 시작. 새 코드가 망가졌거나 이미지가 더 새 버전이면 이미지 버전으로 실행
  - 업데이트 직전 자동 백업 (백업 암호를 정해 둔 경우)
- `homeops-update`가 처음 설치할 때 쓴 데이터 폴더와 포트를 유지 (전에는 기본값으로 돌아갈 수 있었음)
- `docker-compose.yml`에 `pull_policy: build` 추가 — Portainer에서 다시 배포할 때 이미지를 새로 빌드

### v0.6.1 — 2026-11-01
- **Synology 2단계 인증 계정 지원**: 처음 한 번 OTP 코드를 넣고 저장하면 DSM의 "신뢰할 수 있는 기기"로 등록되어 이후에는 코드 없이 로그인 (DSM 6 · 7)
- 연결 테스트에서 OTP를 확인한 뒤 저장해도 같은 코드를 다시 요구하지 않음
- DSM 로그인 오류를 원인별로 안내 (비밀번호 틀림, OTP 필요, OTP 틀림, IP 차단 등)
- 연동 플러그인에 저장 직전 설정을 고치는 `before_save()`와 화면에 안 보이는 저장값(`hidden`) 추가

### v0.6.0 — 2026-11-01
- **연동을 플러그인 구조로 변경** — 새 시스템은 `app/integrations/`에 파일 하나만 추가하면 화면(연결 추가 목록, 입력 폼, 상태 카드, 작업 버튼)이 자동으로 만들어짐
- **모든 종류를 여러 개씩 연결** 가능 (예: Proxmox 2대, NAS 2대)
- 새 연동
  - **UniFi Network** (UDR 등 UniFi OS 콘솔, 공식 Integration API): 장치 상태 · 클라이언트 수 · 장치 재시작
  - **VMware vCenter** (7.0 U2 이상 REST API): 호스트 · VM 목록, VM 켜기 · 강제 끄기, 게스트 종료 · 재시작
  - **웹 상태 확인**: 전용 연동이 없는 장비 · 서비스의 응답 여부와 웹 화면 바로가기 (인프라 / 스마트홈 허브 중 표시할 메뉴 선택)
- 모든 상태 카드에 "웹 화면 열기" 바로가기
- 연동 경로의 상태 확인 대상을 연결 목록에서 고르도록 변경
- v0.5 이하에서 저장한 연결 설정은 처음 실행할 때 새 구조로 자동 이전 (토큰 유지)

### v0.5.1 — 2026-11-01
- 업데이트 후에도 브라우저가 예전 화면을 보여 주던 문제 수정 (화면 파일을 매번 새 버전인지 확인)
- 왼쪽 메뉴 아래에 현재 버전 표시

### v0.5.0 — 2026-11-01
- **아무것도 없는 상태로 시작**
  - 기본으로 들어가던 수동 등록 기기 · 플랫폼 역할 · 연동 경로 예시 데이터 제거
  - 인프라 · 스마트홈 허브 화면은 연결한 시스템만 표시 (연결 전 빈 카드 없음)
  - 빈 화면에서 바로 "+ Proxmox VE", "+ Hubitat 허브"처럼 눌러 연결 설정으로 이동, 입력 폼이 열린 상태로 시작
  - 스마트홈 연동 화면은 기기를 가져올 연결(Hubitat Maker API · Home Assistant)이 생기기 전까지 연결 안내만 표시
- 왼쪽 메뉴를 "인프라 · 스마트홈 허브 · 스마트홈 연동" 세 항목으로 단순화

### v0.4.0 — 2026-11-01
- **연결 설정을 "필요한 것만 추가" 방식으로 변경**
  - 처음 화면은 "무엇부터 연결할까요?"에서 시스템 종류를 고르는 것으로 시작
  - 추가한 연결만 접힌 카드(이름 · 주소 · 상태)로 표시, 카드에서 바로 연결 테스트 · 편집 · 삭제
  - **+ 연결 추가**로 Hubitat 허브는 여러 대, 나머지는 하나씩 추가
  - 알림 기준 · 관리자 비밀번호는 접어 두는 "알림 · 계정" 영역으로 이동
- 백업의 원격 저장소도 **+ 저장소 추가**로 FTP · WebDAV 중 쓰는 것만 추가 (삭제해도 이미 올라간 파일은 유지)

### v0.3.1 — 2026-11-01
- **Docker 없이 LXC에 바로 설치**하는 `install.sh` 추가 (Python 가상환경 + systemd 서비스, 데이터는 `/var/lib/homeops`)
- `homeops-update` 명령으로 업데이트
- Docker 설치는 Portainer 스택(Repository)으로 바로 올릴 수 있도록 데이터 저장을 이름 있는 볼륨(`homeops-data`)으로 변경
- Python 3.11(Debian 12 기본)에서도 동작 확인

### v0.3.0 — 2026-11-01
- **백업 · 복구** 메뉴 추가
  - 지금 백업, 매일 정해진 시각 자동 백업 (시간대 설정)
  - 로컬 저장과 함께 **FTP(FTPS) · WebDAV** 업로드, 연결 테스트, 저장 폴더 자동 생성
  - 백업 파일 전체를 백업 암호로 암호화 (토큰·비밀번호 보호)
  - 로컬·원격 보관 개수 자동 정리
  - 로컬·FTP·WebDAV 목록 또는 업로드한 파일로 복구, 복구 직전 상태 자동 백업
  - Hubitat 허브 백업 파일 포함 옵션
- 다른 설치(다른 암호화 키)로 옮겨도 토큰을 그대로 쓸 수 있도록 키를 함께 복구
- 시간 입력 등 기본 입력 요소를 어두운 테마로 표시

### v0.2.0 — 2026-11-01
- 첫 접속 때 웹에서 관리자 계정 만들기, 비밀번호 변경
- **연결 설정** 화면: Hubitat 허브 추가·삭제, HA · Homebridge · NAS · Proxmox · Portainer 입력과 연결 테스트
- 연결 정보를 DB에 저장하고 토큰·비밀번호는 암호화 (`data/secret.key` 자동 생성), 저장 즉시 반영
- `.env` · `config.yaml` 없이 `docker compose up`만으로 실행
- 로그인 실패 메시지가 표시되지 않던 문제 수정

### v0.1.0 — 2026-11-01
- 첫 버전: 인프라(Synology NAS · Proxmox VE · Portainer), 스마트홈 허브(Hubitat · Home Assistant · Homebridge), 스마트홈 연동(연동 경로 · 기기 제어 · 알림)
- 수동 등록 기기 · 플랫폼 역할 · 연동 경로 관리
- 관리자 로그인, 위험 작업 확인 창, 작업 기록
- Docker · docker-compose 배포

