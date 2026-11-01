#!/bin/sh
# 1) 웹에서 받아 둔 새 코드(/app/data/code)가 이미지보다 새 버전이면 그것으로 실행한다.
# 2) data 폴더 권한을 맞춘 뒤 일반 사용자(homeops)로 실행한다.
set -e
CODE=/app/data/code
ROOT=/app

newer() {  # newer <디렉터리> : 그 디렉터리의 VERSION 이 이미지 것보다 크면 0
  python - "$1" <<'EOF'
import pathlib, re, sys
def v(p):
    try:
        m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)', pathlib.Path(p).read_text(), re.M)
    except OSError:
        return ()
    return tuple(int(x) for x in re.findall(r"\d+", m.group(1))) if m else ()
sys.exit(0 if v(sys.argv[1] + "/app/__init__.py") > v("/app/app/__init__.py") else 1)
EOF
}

if [ -f "$CODE/app/__init__.py" ] && newer "$CODE"; then
  ok=1
  # 의존성이 바뀌었으면 설치 (컨테이너가 다시 만들어질 때마다 한 번)
  if [ -f "$CODE/requirements.txt" ] && ! cmp -s "$CODE/requirements.txt" /app/requirements.txt \
     && ! cmp -s "$CODE/requirements.txt" /tmp/.homeops-req; then
    if [ "$(id -u)" = "0" ] && pip install -q --no-cache-dir -r "$CODE/requirements.txt"; then
      cp "$CODE/requirements.txt" /tmp/.homeops-req
    else
      echo "HomeOps: 새 버전 의존성 설치 실패 — 이미지에 들어 있는 버전으로 실행합니다" >&2
      ok=0
    fi
  fi
  if [ "$ok" = "1" ] && (cd "$CODE" && python -c "import app.main") ; then
    ROOT="$CODE"
    echo "HomeOps: 업데이트된 코드로 실행합니다 ($CODE)"
  elif [ "$ok" = "1" ]; then
    echo "HomeOps: 새 코드를 불러오지 못해 이미지에 들어 있는 버전으로 실행합니다" >&2
  fi
fi
cd "$ROOT"

if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/data
  chown -R homeops:homeops /app/data
  exec setpriv --reuid=homeops --regid=homeops --init-groups "$@"
fi
exec "$@"
