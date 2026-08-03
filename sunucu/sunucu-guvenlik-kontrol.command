#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/ortak.sh"

read -r -d '' REMOTE_SCRIPT <<'REMOTE' || true
set -euo pipefail

line() { printf '%s\n' "----------------------------------------------------------------"; }
check_file() {
  local path="$1"
  if [ -e "$path" ]; then
    stat -c '%a %U:%G %n' "$path"
  else
    printf 'YOK %s\n' "$path"
  fi
}

printf 'Final1 güvenlik ve yayın kontrolü\n'
date -Is
line
printf 'Servisler:\n'
systemctl is-active final1-web final1-worker final1-manager aysegul nginx || true
line
printf 'Final1 service hardening özet:\n'
systemctl show final1-web \
  -p User -p Group -p NoNewPrivileges -p PrivateTmp -p ProtectHome -p ProtectSystem \
  -p CapabilityBoundingSet -p UMask -p RestrictSUIDSGID -p PrivateDevices \
  -p ReadWritePaths --no-pager || true
line
printf 'Dosya izinleri:\n'
check_file /etc/final1
check_file /etc/final1/final1.env
check_file /etc/final1/tls
check_file /etc/final1/tls/final1.origin.crt
check_file /etc/final1/tls/final1.origin.key
check_file /var/lib/final1
check_file /var/lib/final1/tradertrailing.db
check_file /var/log/final1
line
printf 'Açık dinleme portları:\n'
ss -tlnp | grep -E ':(22|80|443|8000|8081|4001)\s' || true
line
printf 'Nginx domainleri:\n'
grep -n 'server_name' /etc/nginx/sites-available/final1.conf || true
line
printf 'Firewall:\n'
ufw status verbose || true
line
printf 'Nginx yapılandırma testi:\n'
nginx -t || true
line
printf 'Uygulama sağlık testi:\n'
curl -fsS --max-time 5 http://127.0.0.1:8000/api/health || true
printf '\n'
REMOTE

ssh "${SSH_ARGS[@]}" "$(remote_target)" "bash -s" <<<"$REMOTE_SCRIPT"

