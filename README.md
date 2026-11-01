# HomeOps

홈랩 인프라와 스마트홈 허브를 한 화면에서 보고 관리하는 웹앱입니다.

| 메뉴 | 대상 | 할 수 있는 일 |
|---|---|---|
| **인프라** | Synology NAS · Proxmox VE · Portainer | 볼륨·디스크·CPU·메모리 확인, NAS 재부팅 / VM·LXC 시작·종료·재시작·스냅샷·백업 / 컨테이너 시작·중지·재시작·로그, 스택 시작·중지 |
| **스마트홈 허브** | Hubitat(여러 대) · Home Assistant · Homebridge + 수동 등록 기기 | 허브 상태·펌웨어·메모리·온도, 허브 백업(파일 보관)·재부팅, HA 백업·재시작, Homebridge 재시작 / API가 없는 기기(Apple TV, HomePod, Nest Hub, Aqara 허브 등)를 역할과 함께 등록하고 ping으로 응답 확인 / 플랫폼별 용도·기능·연결 경로 정리 |
| **스마트홈 연동** | 플랫폼 간 연동 경로 · 기기 | 연동 경로별 상태, 방별 기기 목록과 켜기/끄기, 배터리 부족·외출 중 열린 문·허브 무응답 알림 |

- 재부팅·종료·중지 같은 위험한 작업은 확인 창을 한 번 더 거치고, 모든 제어 작업은 **작업 기록**에 남습니다.
- 휴대폰에서는 하단 탭 메뉴로 바뀝니다 (홈 화면에 추가해 앱처럼 쓸 수 있음).
- 수동 등록 기기·플랫폼 역할·연동 경로는 첫 실행 때 기본값이 들어가고, 이후 화면에서 편집합니다 (`app/seed_default.yaml`).

## 구성

```
FastAPI (Python 3.13) ── httpx ──▶ Hubitat Maker API / 허브 관리 URL
   │                              Home Assistant REST
   │                              Homebridge config-ui-x API
   │                              Synology DSM Web API
   │                              Proxmox VE API (토큰)
   │                              Portainer API (토큰)
   ├─ SQLite (data/homeops.db): 수동 등록 기기 · 플랫폼 역할 · 연동 경로 · 작업 기록
   └─ 정적 웹 화면 (app/static, 빌드 과정 없음)
```

연결 정보(토큰·비밀번호)는 서버의 `config/config.yaml`에만 있고 브라우저로 내려가지 않습니다.

## 설치 (Proxmox LXC + Docker)

### 1. LXC 준비

Proxmox에서 Debian 12 LXC를 만듭니다 (1 vCPU · 512MB~1GB RAM · 4GB 디스크면 충분).
옵션 → 기능에서 **nesting**과 **keyctl**을 켜야 LXC 안에서 Docker가 동작합니다.

```bash
apt update && apt install -y curl git
curl -fsSL https://get.docker.com | sh
```

### 2. 코드 받기와 설정

```bash
git clone https://github.com/kwon2288/HomeOps.git /opt/homeops
cd /opt/homeops
cp .env.example .env
cp config/config.example.yaml config/config.yaml
```

`.env`에서 다음을 채웁니다.

```bash
HOMEOPS_ADMIN_PASSWORD=원하는-비밀번호
HOMEOPS_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))" 로 만든 값)
HOMEOPS_COOKIE_SECURE=false   # NPM + HTTPS 뒤에 두면 true
```

`config/config.yaml`에 각 시스템의 주소와 토큰을 넣습니다 (아래 [연결 방법](#연결-방법)). 쓰지 않는 시스템은 항목을 지우면 화면에 "연결 전"으로 나옵니다.

### 3. 실행

```bash
docker compose up -d --build
docker compose logs -f
```

`http://<LXC IP>:8080` 으로 접속해 로그인합니다.

업데이트:

```bash
cd /opt/homeops && git pull && docker compose up -d --build
```

### 4. 외부 접속 (권장: NPM + HTTPS)

이 앱은 허브 재부팅이나 컨테이너 중지까지 할 수 있으므로 **HTTP로 바로 포트포워딩하지 마세요.**

1. Nginx Proxy Manager에 Proxy Host 추가 → `http://<LXC IP>:8080`, SSL 인증서 발급, Force SSL 켜기
2. `.env`에서 `HOMEOPS_COOKIE_SECURE=true` 로 바꾸고 `docker compose up -d`
3. 가능하면 Cloudflare Access(또는 국가 제한 + WAF 규칙)를 앞에 한 겹 더 두는 것을 권합니다.

로그인은 5번 틀리면 해당 IP가 5분간 잠깁니다.

## 연결 방법

### Hubitat (허브마다)
1. 허브 웹 → **Apps → Add Built-In App → Maker API**
2. "Allow Access via Local IP Address" 켜기, 관리할 기기 선택 → 완료
3. 화면 아래 예시 URL의 `/apps/api/<App ID>/...?access_token=<토큰>`에서 App ID와 토큰을 `maker_api`에 입력
4. 허브에 로그인 보안을 켰다면 `login`에 허브 계정 입력

> 기기 목록·제어·모드·HSM은 공식 Maker API를 씁니다. 메모리·온도·DB 크기·펌웨어·재부팅·백업은 허브 관리 화면이 쓰는 **비공식 URL**(`/hub/advanced/*`, `/hub2/hubData`, `/hub/reboot`, `/hub/backupDB`)이라 펌웨어 업데이트 후 동작이 달라질 수 있습니다. 값이 안 나오면 "—"로 표시되고 나머지 기능은 그대로 동작합니다.

허브 백업 파일은 `data/backups/`에 허브별로 `HOMEOPS_BACKUP_KEEP`개(기본 10개)까지 보관되고, 허브 화면에서 내려받을 수 있습니다.

### Home Assistant
프로필 → 보안 → **장기 액세스 토큰** 생성 → `home_assistant.token`.
백업은 HA OS(Supervisor)의 `hassio.backup_full` 서비스를 호출합니다.

### Homebridge
config-ui-x 로그인 계정을 `homebridge`에 입력합니다.
기기 목록의 **HB 배지**(HomeKit에 노출 중)와 액세서리 수는 Homebridge를 **insecure 모드(-I)**로 실행했을 때만 나옵니다. 배지는 Hubitat/HA 기기 이름과 Homebridge 액세서리 이름이 같을 때 붙습니다.

### Synology NAS
제어판 → 사용자에서 **HomeOps 전용 계정**을 만들고(2단계 인증 끄기). 재부팅과 스토리지 정보 조회는 관리자 권한이 있어야 하므로 administrators 그룹에 넣되, 필요 없는 앱·공유 폴더 권한은 막아 두세요. `synology`에 입력합니다. 자체 서명 인증서면 `verify_ssl: false`.

### Proxmox VE
Datacenter → Permissions → **API Tokens** → 추가 (Privilege Separation 켬)
토큰에 역할을 줄 때 권장 권한: `VM.Audit, VM.PowerMgmt, VM.Snapshot, VM.Backup, Datastore.Audit, Datastore.AllocateSpace, Sys.Audit`
`token_id`는 `사용자@realm!토큰이름` 형식입니다. 백업은 `backup_storage`(기본 `local`)에 snapshot 모드, zstd 압축으로 만듭니다.

### Portainer
My account → **Access tokens** → 추가 → `portainer.api_key`.

## 개발

```bash
pip install -r requirements-dev.txt
pytest

export HOMEOPS_ADMIN_PASSWORD=dev HOMEOPS_SECRET_KEY=dev HOMEOPS_COOKIE_SECURE=false
uvicorn app.main:get_app --factory --reload --port 8080
```

```
app/
  main.py            앱 생성, 라우터 연결
  config.py          config.yaml · 환경 변수
  auth.py            로그인 (서명 쿠키, 실패 잠금)
  core.py            공통 헬퍼 (상태 감싸기, 작업 기록, ping)
  db.py              SQLite
  seed_default.yaml  첫 실행 기본값
  connectors/        시스템별 API 클라이언트
  routers/           infra · hubs · registry · smarthome
  static/            웹 화면 (index.html, app.css, app.js)
tests/               pytest (외부 API는 respx로 흉내)
```

### 주요 API

| 경로 | 설명 |
|---|---|
| `GET /api/infra` | NAS · Proxmox · Portainer 상태 |
| `GET /api/hubs` | Hubitat · HA · Homebridge 상태 |
| `GET /api/smarthome` | 모드 · HSM · 연동 경로 상태 · 기기 · 알림 |
| `POST /api/smarthome/devices/{HE\|HA}/{hub}/{id}/{on\|off}` | 기기 켜기/끄기 |
| `GET/POST/PUT/DELETE /api/registry/{devices\|platforms\|paths}` | 수동 등록 · 플랫폼 역할 · 연동 경로 |
| `GET /api/audit` | 작업 기록 |

위험한 작업(재부팅·종료·중지·재시작)은 본문에 `{"confirm": true}`가 있어야 실행됩니다.
