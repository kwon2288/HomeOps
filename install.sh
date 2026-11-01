#!/usr/bin/env bash
# HomeOps 설치 · 업데이트 (Docker 없이 Debian/Ubuntu LXC에 바로 설치)
#
#   git clone https://github.com/kwon2288/HomeOps.git /opt/homeops
#   /opt/homeops/install.sh
#
# 다시 실행하면 업데이트(의존성 설치 + 서비스 재시작)만 합니다.
# 데이터는 /var/lib/homeops 에 있어서 코드 업데이트와 상관없이 유지됩니다.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${HOMEOPS_DATA:-/var/lib/homeops}"
PORT="${HOMEOPS_PORT:-8080}"
SERVICE=/etc/systemd/system/homeops.service
SKIP_SYSTEMD="${SKIP_SYSTEMD:-0}"   # 테스트용

say() { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }

if [ "$(id -u)" != "0" ]; then
  echo "root로 실행하세요 (sudo $0)" >&2
  exit 1
fi

say "필요한 패키지 설치 (python3, venv, ping, git)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv iputils-ping git ca-certificates >/dev/null

PYV="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Python 3.11 이상이 필요합니다 (현재 $PYV). Debian 12 이상 또는 Ubuntu 24.04 LXC를 쓰세요." >&2
  exit 1
fi

say "서비스 계정과 데이터 폴더 ($DATA_DIR)"
id homeops >/dev/null 2>&1 || useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin homeops
mkdir -p "$DATA_DIR"
chown -R homeops:homeops "$DATA_DIR"
chmod 700 "$DATA_DIR"

say "Python 가상환경과 의존성 (Python $PYV)"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

cat > /usr/local/bin/homeops-update <<EOF
#!/usr/bin/env bash
# HomeOps 최신 버전으로 업데이트
set -euo pipefail
cd "$APP_DIR"
git pull --ff-only
exec "$APP_DIR/install.sh"
EOF
chmod 755 /usr/local/bin/homeops-update

if [ "$SKIP_SYSTEMD" = "1" ]; then
  say "SKIP_SYSTEMD=1 — 서비스 등록은 건너뜀"
  exit 0
fi

say "systemd 서비스 등록 (포트 $PORT)"
cat > "$SERVICE" <<EOF
[Unit]
Description=HomeOps - 홈랩 · 스마트홈 통합 관리
After=network-online.target
Wants=network-online.target

[Service]
User=homeops
Group=homeops
WorkingDirectory=$APP_DIR
Environment=HOMEOPS_DATA=$DATA_DIR
EnvironmentFile=-/etc/default/homeops
ExecStart=$APP_DIR/.venv/bin/uvicorn app.main:get_app --factory --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips *
Restart=on-failure
RestartSec=3
# 보안: 데이터 폴더 말고는 쓰기 금지, ping용 권한만 허용
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=$DATA_DIR
AmbientCapabilities=CAP_NET_RAW
CapabilityBoundingSet=CAP_NET_RAW

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now homeops >/dev/null 2>&1 || true
systemctl restart homeops

for _ in $(seq 1 20); do
  if python3 -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:$PORT/api/health', timeout=1)" 2>/dev/null; then
    IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    say "완료: http://${IP:-<LXC IP>}:$PORT 에 접속하세요"
    echo "  상태 확인: systemctl status homeops   로그: journalctl -u homeops -f"
    echo "  업데이트:  homeops-update"
    exit 0
  fi
  sleep 1
done
echo "서비스가 응답하지 않습니다. 로그를 확인하세요: journalctl -u homeops -n 50" >&2
exit 1
