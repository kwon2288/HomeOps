#!/bin/sh
# data 폴더 권한을 맞춘 뒤 일반 사용자(homeops)로 실행한다.
set -e
if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/data
  chown -R homeops:homeops /app/data
  exec setpriv --reuid=homeops --regid=homeops --init-groups "$@"
fi
exec "$@"
