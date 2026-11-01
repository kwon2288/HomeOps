# HomeOps

홈랩 인프라와 스마트홈 허브를 한 화면에서 보고 관리하는 웹앱입니다.
설치 후에는 **계정 만들기부터 모든 연결 설정까지 웹 화면에서** 합니다. 설정 파일을 직접 고칠 일이 없습니다.

| 메뉴 | 대상 | 할 수 있는 일 |
|---|---|---|
| **인프라** | Synology NAS · Proxmox VE · Portainer | 볼륨·디스크·CPU·메모리 확인, NAS 재부팅 / VM·LXC 시작·종료·재시작·스냅샷·백업 / 컨테이너 시작·중지·재시작·로그, 스택 시작·중지 |
| **스마트홈 허브** | Hubitat(여러 대) · Home Assistant · Homebridge + 수동 등록 기기 | 허브 상태·펌웨어·메모리·온도, 허브 백업(파일 보관)·재부팅, HA 백업·재시작, Homebridge 재시작 / API가 없는 기기(Apple TV, HomePod, Nest Hub, Aqara 허브 등)를 역할과 함께 등록하고 ping으로 응답 확인 / 플랫폼별 용도·기능·연결 경로 정리 |
| **스마트홈 연동** | 플랫폼 간 연동 경로 · 기기 | 연동 경로별 상태, 방별 기기 목록과 켜기/끄기, 배터리 부족·외출 중 열린 문·허브 무응답 알림 |
| **연결 설정** | 위 모든 시스템 | 주소·토큰 입력, 저장 전 **연결 테스트**, Hubitat 허브 추가·삭제, 알림 기준, 관리자 비밀번호 변경 |

- 재부팅·종료·중지 같은 위험한 작업은 확인 창을 한 번 더 거치고, 모든 제어·설정 변경은 **작업 기록**에 남습니다.
- 휴대폰에서는 하단 탭 메뉴로 바뀝니다 (홈 화면에 추가해 앱처럼 쓸 수 있음).
- 토큰·비밀번호는 암호화해서 저장하고, 화면에는 "저장됨"으로만 표시합니다. 바꿀 때만 새로 입력하면 됩니다.

## 설치 (Proxmox LXC + Docker)

### 1. LXC 준비

Proxmox에서 Debian 12 LXC를 만듭니다 (1 vCPU · 512MB~1GB RAM · 4GB 디스크면 충분).
옵션 → 기능에서 **nesting**과 **keyctl**을 켜야 LXC 안에서 Docker가 동작합니다.

```bash
apt update && apt install -y curl git
curl -fsSL https://get.docker.com | sh
```

### 2. 실행

```bash
git clone https://github.com/kwon2288/HomeOps.git /opt/homeops
cd /opt/homeops
docker compose up -d --build
```

### 3. 웹에서 설정

1. `http://<LXC IP>:8080` 접속 → **관리자 계정 만들기** (처음 한 번만 나오는 화면)
2. 자동으로 **연결 설정** 화면이 열립니다. 쓰는 시스템만 입력하고 **연결 테스트 → 저장**
3. 저장하는 즉시 각 메뉴에 반영됩니다 (재시작 필요 없음)

> 처음 계정 만들기 화면은 계정이 없을 때 누구나 열 수 있습니다. 설치 직후 바로 계정을 만들고, 그 전에는 외부에 열지 마세요.

업데이트:

```bash
cd /opt/homeops && git pull && docker compose up -d --build
```

데이터(계정, 연결 설정, 수동 등록 기기, 작업 기록, 허브 백업 파일)는 모두 `data/` 폴더에 있습니다. LXC를 옮길 때는 이 폴더만 복사하면 됩니다. `data/secret.key`가 없으면 저장된 토큰을 풀 수 없으니 함께 백업하세요.

### 외부 접속 (권장: NPM + HTTPS)

이 앱은 허브 재부팅이나 컨테이너 중지까지 할 수 있으므로 **HTTP로 바로 포트포워딩하지 마세요.**

1. Nginx Proxy Manager에 Proxy Host 추가 → `http://<LXC IP>:8080`, SSL 인증서 발급, Force SSL 켜기
2. 가능하면 Cloudflare Access(또는 국가 제한 + WAF 규칙)를 앞에 한 겹 더 두는 것을 권합니다.

HTTPS로 접속하면 로그인 쿠키가 자동으로 Secure로 설정됩니다. 로그인은 5번 틀리면 해당 IP가 5분간 잠깁니다.

## 연결 정보 준비하기

연결 설정 화면의 각 카드에도 같은 안내가 있습니다.

| 시스템 | 필요한 것 | 만드는 곳 |
|---|---|---|
| Hubitat (허브마다) | 허브 주소, Maker API App ID · Access Token | 허브 웹 → Apps → Add Built-In App → **Maker API** ("Allow Access via Local IP Address" 켜기, 관리할 기기 선택). 예시 URL `/apps/api/<App ID>/...?access_token=<토큰>` |
| Home Assistant | 주소, 장기 액세스 토큰 | HA 프로필 → 보안 → 장기 액세스 토큰 |
| Homebridge | 주소, UI 로그인 계정 | config-ui-x 계정. 액세서리 목록·HB 배지는 insecure 모드(-I) 필요 |
| Synology NAS | 주소, 전용 계정 | 제어판 → 사용자. 2단계 인증 끄기, 재부팅·스토리지 조회에 관리자 그룹 필요 |
| Proxmox VE | 주소, 토큰 ID · Secret | Datacenter → Permissions → API Tokens. 권장 권한: VM.Audit, VM.PowerMgmt, VM.Snapshot, VM.Backup, Datastore.Audit, Datastore.AllocateSpace, Sys.Audit |
| Portainer | 주소, Access Token | My account → Access tokens |

### Hubitat 참고

- 기기 목록·제어·모드·HSM은 공식 **Maker API**를 씁니다.
- 메모리·온도·DB 크기·펌웨어·재부팅·백업은 허브 관리 화면이 쓰는 **비공식 URL**(`/hub/advanced/*`, `/hub2/hubData`, `/hub/reboot`, `/hub/backupDB`)이라 펌웨어 업데이트 후 동작이 달라질 수 있습니다. 값이 안 나오면 "—"로 표시되고 나머지 기능은 그대로 동작합니다.
- 허브에 로그인 보안을 켰다면 허브 카드에 허브 로그인 계정도 입력하세요.
- 허브 백업 파일은 `data/backups/`에 허브별로 10개까지 보관되고, 허브 화면에서 내려받을 수 있습니다.

## 고급: 환경 변수 (모두 선택)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `HOMEOPS_COOKIE_SECURE` | `auto` | `auto`는 HTTPS로 접속할 때만 Secure 쿠키. `true`/`false`로 고정 가능 |
| `HOMEOPS_BACKUP_KEEP` | `10` | Hubitat 백업 파일 보관 개수 (허브별) |
| `HOMEOPS_SECRET_KEY` | 자동 생성 | 지정하지 않으면 `data/secret.key`를 만들어 씁니다 |
| `HOMEOPS_ADMIN_USER` / `HOMEOPS_ADMIN_PASSWORD` | 없음 | 웹 계정 대신 고정 계정을 쓰고 싶을 때만. 지정하면 웹 계정 만들기·비밀번호 변경이 꺼집니다 |
| `HOMEOPS_SEED` | 없음 | 수동 등록 기기·플랫폼 역할·연동 경로의 첫 기본값 파일 (기본: `app/seed_default.yaml`) |

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
  auth.py            첫 실행 계정 만들기, 로그인, 비밀번호 변경
  core.py            공통 헬퍼 (상태 감싸기, 작업 기록, ping)
  db.py              SQLite
  seed_default.yaml  첫 실행 기본값
  connectors/        시스템별 API 클라이언트
  routers/           infra · hubs · registry · smarthome · settings
  static/            웹 화면 (index.html, app.css, app.js — 빌드 과정 없음)
tests/               pytest (외부 API는 respx로 흉내)
```

### 주요 API

| 경로 | 설명 |
|---|---|
| `GET /api/auth/status` · `POST /api/auth/setup` | 첫 실행 여부 · 관리자 계정 만들기 |
| `GET /api/settings` · `PUT /api/settings/{section}` | 연결 설정 조회(비밀값 가림) · 섹션별 저장 (`null`이면 연결 해제) |
| `POST /api/settings/test/{section}` | 저장하지 않고 연결만 시험 |
| `GET /api/infra` · `GET /api/hubs` · `GET /api/smarthome` | 메뉴별 상태 |
| `POST /api/smarthome/devices/{HE\|HA}/{hub}/{id}/{on\|off}` | 기기 켜기/끄기 |
| `GET/POST/PUT/DELETE /api/registry/{devices\|platforms\|paths}` | 수동 등록 · 플랫폼 역할 · 연동 경로 |
| `GET /api/audit` | 작업 기록 |

위험한 작업(재부팅·종료·중지·재시작)은 본문에 `{"confirm": true}`가 있어야 실행됩니다.
