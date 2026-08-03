#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
EXPECTED_PROJECT_DIR="${EXPECTED_PROJECT_DIR:-ayserose1}"
FRONTEND_ONLY="${FRONTEND_ONLY:-0}"

if [ "$(basename "${PROJECT_ROOT}")" != "${EXPECTED_PROJECT_DIR}" ]; then
  echo "HATA: Yayin yalnizca ${EXPECTED_PROJECT_DIR} proje klasorunden yapilabilir."
  echo "Bulunan klasor: ${PROJECT_ROOT}"
  exit 1
fi

cd "${PROJECT_ROOT}"

SERVER_HOST="${SERVER_HOST:-178.210.168.102}"
SERVER_USER="${SERVER_USER:-root}"
SSH_PORT="${SSH_PORT:-22666}"
KEY_FILE="${KEY_FILE:-${HOME}/.ssh/aysegul_sunucu_ed25519}"
APP_NAME="${APP_NAME:-final1}"
APP_USER="${APP_USER:-final1app}"
APP_ROOT="${APP_ROOT:-/opt/${APP_NAME}}"
REMOTE_DIR="${APP_ROOT}/current"
APP_DATA="${APP_DATA:-/var/lib/${APP_NAME}}"
APP_LOG="${APP_LOG:-/var/log/${APP_NAME}}"
APP_ENV_FILE="${APP_ENV_FILE:-/etc/${APP_NAME}/${APP_NAME}.env}"
MARKETING_ROOT="${MARKETING_ROOT:-/var/www/${APP_NAME}-marketing}"
WEB_PORT="${WEB_PORT:-8000}"
PUBLIC_TEST_PORT="${PUBLIC_TEST_PORT:-8081}"
SERVER_NAMES="${SERVER_NAMES:-ayserose.com www.ayserose.com}"
MARKETING_SERVER_NAMES="${MARKETING_SERVER_NAMES:-omeraltin.com www.omeraltin.com}"
SYNC_ENV="${SYNC_ENV:-first}"
SYNC_DB_ON_FIRST_DEPLOY="${SYNC_DB_ON_FIRST_DEPLOY:-1}"
SESSION_TTL_DAYS="${SESSION_TTL_DAYS:-3650}"
AUTH_COOKIE_MAX_AGE_SEC="${AUTH_COOKIE_MAX_AGE_SEC:-315360000}"
BINANCE_API_BASE_URL="${BINANCE_API_BASE_URL:-https://api1.binance.com}"

echo "ayserose arayuzu yayin icin dogrulaniyor..."
DASHBOARD_DIR="${PROJECT_ROOT}/ui/dashboard-react"
if [ ! -f "${DASHBOARD_DIR}/package.json" ]; then
  echo "HATA: Arayuz projesi bulunamadi: ${DASHBOARD_DIR}"
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "HATA: Arayuzu derlemek icin npm bulunamadi."
  exit 1
fi
if [ ! -d "${DASHBOARD_DIR}/node_modules" ]; then
  (cd "${DASHBOARD_DIR}" && npm ci --no-audit --no-fund)
fi
(cd "${DASHBOARD_DIR}" && npm run verify)
if [ ! -s "${PROJECT_ROOT}/ui/assets/v2/dashboard/index.html" ]; then
  echo "HATA: Dogrulanmis arayuz cikisi olusmadi."
  exit 1
fi
echo "ayserose arayuzu hazir."

SSH_OPTS=(-p "${SSH_PORT}" -o ConnectTimeout=20 -o ServerAliveInterval=10 -o StrictHostKeyChecking=accept-new)
SCP_OPTS=(-O -P "${SSH_PORT}" -o ConnectTimeout=20 -o ServerAliveInterval=10 -o StrictHostKeyChecking=accept-new)
RSYNC_RSH="ssh -p ${SSH_PORT} -o ConnectTimeout=20 -o ServerAliveInterval=10 -o StrictHostKeyChecking=accept-new"

if [ -f "${KEY_FILE}" ]; then
  SSH_OPTS+=(-i "${KEY_FILE}" -o IdentitiesOnly=yes)
  SCP_OPTS+=(-i "${KEY_FILE}" -o IdentitiesOnly=yes)
  RSYNC_RSH="${RSYNC_RSH} -i ${KEY_FILE} -o IdentitiesOnly=yes"
else
  echo "UYARI: SSH anahtari bulunamadi: ${KEY_FILE}"
  echo "Sunucu sifresi istenebilir."
fi

SSH_ARGS=("${SSH_OPTS[@]}" "${SERVER_USER}@${SERVER_HOST}")

build_allowed_origins() {
  local origins="http://${SERVER_HOST}:${PUBLIC_TEST_PORT}"
  local host
  for host in ${SERVER_NAMES}; do
    [ "${host}" = "_" ] && continue
    origins="${origins},http://${host},https://${host}"
  done
  printf '%s\n' "${origins}"
}

first_public_base_url() {
  local host
  for host in ${SERVER_NAMES}; do
    [ "${host}" = "_" ] && continue
    printf 'https://%s\n' "${host}"
    return 0
  done
  printf 'http://%s:%s\n' "${SERVER_HOST}" "${PUBLIC_TEST_PORT}"
}

fail_connection() {
  echo ""
  echo "HATA: Sunucuya baglanilamadi (${SERVER_USER}@${SERVER_HOST}:${SSH_PORT})."
  echo "Elle test:"
  echo "  ssh -p ${SSH_PORT} -i ${KEY_FILE} ${SERVER_USER}@${SERVER_HOST}"
  exit 1
}

echo "Sunucu baglantisi kontrol ediliyor..."
if ! ssh "${SSH_ARGS[@]}" "true" >/dev/null 2>&1; then
  fail_connection
fi
echo "Sunucu erisilebilir."

if [ "${FRONTEND_ONLY}" = "1" ]; then
  echo ""
  echo "Dogrulanmis ayserose arayuzu yayinlaniyor..."
  rsync \
    -rltz \
    --delay-updates \
    --omit-dir-times \
    --no-perms \
    --no-owner \
    --no-group \
    --exclude 'dashboard-react/' \
    --exclude '.DS_Store' \
    -e "${RSYNC_RSH}" \
    "${PROJECT_ROOT}/ui/" \
    "${SERVER_USER}@${SERVER_HOST}:${REMOTE_DIR}/ui/"

  ssh "${SSH_ARGS[@]}" \
    "chown -R root:'${APP_USER}' '${REMOTE_DIR}/ui' && find '${REMOTE_DIR}/ui' -type d -exec chmod 750 {} + && find '${REMOTE_DIR}/ui' -type f -exec chmod 640 {} +"

  ssh "${SSH_ARGS[@]}" \
    "test -s '${REMOTE_DIR}/ui/assets/v2/dashboard/index.html' && grep -q '/ui/assets/v2/dashboard/index.html' '${REMOTE_DIR}/ui/dashboard.html'"

  if ! curl -fsS --max-time 25 \
    "https://ayserose.com/ui/assets/v2/dashboard/index.html" >/dev/null; then
    echo "HATA: Yeni arayuz dosyasi canli adresten dogrulanamadi."
    exit 1
  fi

  echo "ayserose arayuzu https://ayserose.com altinda yayinlandi."
  exit 0
fi

echo ""
echo "Sunucu kurulum durumu kontrol ediliyor..."
NEEDS_SETUP=0
if ! ssh "${SSH_ARGS[@]}" "test -d '${REMOTE_DIR}' && test -f /etc/systemd/system/${APP_NAME}-web.service && grep -q '${APP_ROOT}/.trader' /etc/systemd/system/${APP_NAME}-web.service && grep -q '^CapabilityBoundingSet=' /etc/systemd/system/${APP_NAME}-web.service && grep -q 'listen 443 ssl' /etc/nginx/sites-available/${APP_NAME}.conf && grep -q 'root ${MARKETING_ROOT}' /etc/nginx/sites-available/${APP_NAME}.conf" >/dev/null 2>&1; then
  NEEDS_SETUP=1
else
  for host in ${SERVER_NAMES} ${MARKETING_SERVER_NAMES}; do
    [ "${host}" = "_" ] && continue
    if ! ssh "${SSH_ARGS[@]}" "test -f /etc/nginx/sites-available/${APP_NAME}.conf && grep -qw '${host}' /etc/nginx/sites-available/${APP_NAME}.conf" >/dev/null 2>&1; then
      NEEDS_SETUP=1
      break
    fi
  done
fi

if [ "${NEEDS_SETUP}" = "1" ]; then
  echo "Final1 sunucu kurulumu bulunamadi; kurulum dosyasi gonderiliyor..."
  scp "${SCP_OPTS[@]}" "deploy/sunucu-kurulum-final1.sh" "${SERVER_USER}@${SERVER_HOST}:/root/final1-sunucu-kurulum.sh"
  ssh "${SSH_ARGS[@]}" "APP_NAME='${APP_NAME}' APP_USER='${APP_USER}' APP_ROOT='${APP_ROOT}' APP_DATA='${APP_DATA}' APP_LOG='${APP_LOG}' MARKETING_ROOT='${MARKETING_ROOT}' WEB_PORT='${WEB_PORT}' PUBLIC_TEST_PORT='${PUBLIC_TEST_PORT}' SSH_PORT='${SSH_PORT}' SERVER_NAMES='${SERVER_NAMES}' MARKETING_SERVER_NAMES='${MARKETING_SERVER_NAMES}' bash /root/final1-sunucu-kurulum.sh"
fi

echo ""
echo "Sunucu env dosyasi hazirlaniyor..."
CONFIG_CHANGED=0
REMOTE_ENV_STATE="$(ssh "${SSH_ARGS[@]}" "if [ ! -f '${APP_ENV_FILE}' ]; then echo missing; elif grep -q '^FINAL1_ENV_PLACEHOLDER=1' '${APP_ENV_FILE}'; then echo placeholder; else echo ready; fi")"
if [ "${SYNC_ENV}" = "always" ] || { [ "${SYNC_ENV}" = "first" ] && [ "${REMOTE_ENV_STATE}" != "ready" ]; }; then
  TMP_ENV="$(mktemp)"
  trap 'rm -f "${TMP_ENV}" "${TMP_DB_BACKUP:-}"' EXIT
  if [ -f ".env" ]; then
    awk -F= '
      BEGIN {
        skip["APP_ENV"]=1
        skip["DATABASE_URL"]=1
        skip["ALLOWED_ORIGINS"]=1
        skip["PUBLIC_BASE_URL"]=1
        skip["WEB_INTERNAL_URL"]=1
        skip["FINAL1_ENV_PLACEHOLDER"]=1
        skip["WEB_UVICORN_WORKERS"]=1
        skip["PARAM_POOL_WARMUP"]=1
      }
      /^[A-Za-z_][A-Za-z0-9_]*=/ {
        if (skip[$1]) next
      }
      { print }
    ' .env > "${TMP_ENV}"
  else
    : > "${TMP_ENV}"
  fi
  {
    echo ""
    echo "APP_ENV=production"
    echo "DATABASE_URL=sqlite:////var/lib/${APP_NAME}/tradertrailing.db"
    echo "WEB_INTERNAL_URL=http://127.0.0.1:${WEB_PORT}"
    echo "ALLOWED_ORIGINS=$(build_allowed_origins)"
    echo "PUBLIC_BASE_URL=$(first_public_base_url)"
    echo "AUTH_COOKIE_SECURE_AUTO=1"
    echo "AUTH_COOKIE_SECURE=1"
    echo "SESSION_TTL_DAYS=${SESSION_TTL_DAYS}"
    echo "AUTH_COOKIE_MAX_AGE_SEC=${AUTH_COOKIE_MAX_AGE_SEC}"
    echo "AUTH_SLIDING_TTL=1"
    echo "BINANCE_API_BASE_URL=${BINANCE_API_BASE_URL}"
    echo "SECURITY_HEADERS_ENABLED=1"
    echo "CSP_ENABLED=1"
    echo "CSP_REPORT_ONLY=1"
    echo "HSTS_ENABLED=1"
    echo "WEB_UVICORN_WORKERS=2"
    echo "PARAM_POOL_WARMUP=0"
  } >> "${TMP_ENV}"
  scp "${SCP_OPTS[@]}" "${TMP_ENV}" "${SERVER_USER}@${SERVER_HOST}:/tmp/${APP_NAME}.env"
  ssh "${SSH_ARGS[@]}" "install -o root -g '${APP_USER}' -m 640 /tmp/${APP_NAME}.env '${APP_ENV_FILE}' && rm -f /tmp/${APP_NAME}.env"
  CONFIG_CHANGED=1
  echo "Env dosyasi sunucuda hazir."
else
  echo "Env dosyasi zaten hazir; uzerine yazilmadi."
fi

echo ""
echo "Sunucu domain origin ayarlari guncelleniyor..."
REMOTE_ALLOWED_ORIGINS="$(build_allowed_origins)"
REMOTE_PUBLIC_BASE_URL="$(first_public_base_url)"
DOMAIN_CONFIG_CHANGED="$(ssh "${SSH_ARGS[@]}" "APP_ENV_FILE='${APP_ENV_FILE}' ALLOWED_ORIGINS='${REMOTE_ALLOWED_ORIGINS}' PUBLIC_BASE_URL='${REMOTE_PUBLIC_BASE_URL}' SESSION_TTL_DAYS='${SESSION_TTL_DAYS}' AUTH_COOKIE_MAX_AGE_SEC='${AUTH_COOKIE_MAX_AGE_SEC}' BINANCE_API_BASE_URL='${BINANCE_API_BASE_URL}' python3 - <<'PY'
import os
from pathlib import Path

path = Path(os.environ['APP_ENV_FILE'])
updates = {
    'ALLOWED_ORIGINS': os.environ['ALLOWED_ORIGINS'],
    'PUBLIC_BASE_URL': os.environ['PUBLIC_BASE_URL'],
    'AUTH_COOKIE_SECURE': '1',
    'SESSION_TTL_DAYS': os.environ['SESSION_TTL_DAYS'],
    'AUTH_COOKIE_MAX_AGE_SEC': os.environ['AUTH_COOKIE_MAX_AGE_SEC'],
    'AUTH_SLIDING_TTL': '1',
    'BINANCE_API_BASE_URL': os.environ['BINANCE_API_BASE_URL'],
}
original = path.read_text(encoding='utf-8')
lines = original.splitlines()
seen = set()
out = []
for line in lines:
    key = line.split('=', 1)[0] if '=' in line else ''
    if key in updates:
        out.append(f'{key}={updates[key]}')
        seen.add(key)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f'{key}={value}')
updated = '\n'.join(out) + '\n'
changed = updated != original
if changed:
    path.write_text(updated, encoding='utf-8')
print('1' if changed else '0')
PY
chown root:'${APP_USER}' '${APP_ENV_FILE}' && chmod 640 '${APP_ENV_FILE}'")"
if [ "${DOMAIN_CONFIG_CHANGED}" = "1" ]; then
  CONFIG_CHANGED=1
fi

echo ""
echo "Ilk veritabani aktarimi kontrol ediliyor..."
REMOTE_DB_STATE="$(ssh "${SSH_ARGS[@]}" "test -s '${APP_DATA}/tradertrailing.db' && echo present || echo missing")"
if [ "${SYNC_DB_ON_FIRST_DEPLOY}" = "1" ] && [ "${REMOTE_DB_STATE}" = "missing" ]; then
  LOCAL_DB=""
  if [ -f ".env" ]; then
    LOCAL_DB_URL="$(grep -E '^DATABASE_URL=sqlite:' .env | tail -n 1 | sed 's/^DATABASE_URL=//')"
    case "${LOCAL_DB_URL}" in
      sqlite:////*) LOCAL_DB="/${LOCAL_DB_URL#sqlite:////}" ;;
      sqlite:///*) LOCAL_DB="${LOCAL_DB_URL#sqlite:///}" ;;
    esac
  fi
  if [ -n "${LOCAL_DB}" ] && [ -f "${LOCAL_DB}" ]; then
    TMP_DB_BACKUP="$(mktemp)"
    echo "Yerel SQLite veritabani tutarli yedek olarak hazirlaniyor..."
    sqlite3 "${LOCAL_DB}" ".backup '${TMP_DB_BACKUP}'"
    scp "${SCP_OPTS[@]}" "${TMP_DB_BACKUP}" "${SERVER_USER}@${SERVER_HOST}:/tmp/${APP_NAME}.db"
    ssh "${SSH_ARGS[@]}" "install -o '${APP_USER}' -g '${APP_USER}' -m 600 /tmp/${APP_NAME}.db '${APP_DATA}/tradertrailing.db' && rm -f /tmp/${APP_NAME}.db"
    echo "Ilk veritabani aktarildi."
  else
    echo "Yerel SQLite veritabani bulunamadi; sunucuda yeni DB olusturulacak."
  fi
else
  echo "Sunucu veritabani korunuyor."
fi

echo ""
echo "Dosyalar sunucuya gonderiliyor..."

RSYNC_EXCLUDES=(
  --exclude '.DS_Store'
  --exclude '.cursor/'
  --exclude '.env'
  --exclude '.env.*'
  --exclude '.git/'
  --exclude '.github/'
  --exclude '.pytest_cache/'
  --exclude '.ruff_cache/'
  --exclude '.mypy_cache/'
  --exclude '.coverage'
  --exclude '.DS_Store'
  --exclude '.run/'
  --exclude '.venv/'
  --exclude '__pycache__/'
  --exclude 'Kullanıcı Logları/'
  --exclude 'Sistem Logları/'
  --exclude 'archive/'
  --exclude 'artifacts/'
  --exclude '*.pyc'
  --exclude '*.pyo'
  --exclude 'logs/'
  --exclude 'reports/'
  --exclude 'tests/'
  --exclude '/tools/'
  --exclude 'node_modules/'
  --exclude 'ui/dashboard-react/node_modules/'
  --exclude 'data/*.db'
  --exclude 'data/*.db-shm'
  --exclude 'data/*.db-wal'
  --exclude 'data/backups/'
  --exclude 'marketing/visits.json'
  '--filter=protect /logs'
  '--filter=protect /.run'
)

echo "Artimli aktarim izinleri kontrol ediliyor..."
ssh "${SSH_ARGS[@]}" bash <<REMOTE
set -euo pipefail
REMOTE_DIR='${REMOTE_DIR}'
APP_ROOT='${APP_ROOT}'
APP_USER='${APP_USER}'
PERMISSION_MARKER="\${APP_ROOT}/.incremental-sync-v1"

chown root:"\${APP_USER}" "\${REMOTE_DIR}"
chmod 2750 "\${REMOTE_DIR}"
if [ ! -f "\${PERMISSION_MARKER}" ]; then
  find "\${REMOTE_DIR}" -type d -exec chmod g+s {} +
  install -o root -g "\${APP_USER}" -m 640 /dev/null "\${PERMISSION_MARKER}"
fi
REMOTE

RSYNC_COMMON_ARGS=(
  -rltz
  --delay-updates
  --omit-dir-times
  --no-perms
  --no-owner
  --no-group
  --rsync-path="umask 0027 && rsync"
  "${RSYNC_EXCLUDES[@]}"
  -e "${RSYNC_RSH}"
)

RSYNC_CHANGES="$(mktemp)"
trap 'rm -f "${TMP_ENV:-}" "${TMP_DB_BACKUP:-}" "${RSYNC_CHANGES:-}"' EXIT
rsync "${RSYNC_COMMON_ARGS[@]}" \
  --dry-run --itemize-changes --out-format='%i %n%L' \
  ./ "${SERVER_USER}@${SERVER_HOST}:${REMOTE_DIR}/" >"${RSYNC_CHANGES}"

if [ -s "${RSYNC_CHANGES}" ]; then
  CODE_CHANGED=1
  RUNTIME_CHANGED=0
  if grep -qE '(^|[[:space:]])(app|manager_server|marketing|migrations|ops|scripts|shared|ui)/|[[:space:]](alembic\.ini|requirements\.txt|run\.sh)$' "${RSYNC_CHANGES}"; then
    RUNTIME_CHANGED=1
  fi
  echo "Degisen dosyalar aktariliyor..."
  rsync "${RSYNC_COMMON_ARGS[@]}" \
    --itemize-changes --human-readable --stats \
    ./ "${SERVER_USER}@${SERVER_HOST}:${REMOTE_DIR}/"
else
  CODE_CHANGED=0
  RUNTIME_CHANGED=0
  echo "Kod degisikligi yok; dosya aktarimi ve uygulama yeniden baslatma atlandi."
fi

echo ""
echo "Sunucu servisleri guncelleniyor..."
ssh "${SSH_ARGS[@]}" bash <<REMOTE
set -euo pipefail
APP_NAME='${APP_NAME}'
APP_USER='${APP_USER}'
APP_ROOT='${APP_ROOT}'
REMOTE_DIR='${REMOTE_DIR}'
APP_DATA='${APP_DATA}'
APP_LOG='${APP_LOG}'
APP_ENV_FILE='${APP_ENV_FILE}'
MARKETING_ROOT='${MARKETING_ROOT}'
SERVER_NAMES='${SERVER_NAMES}'
MARKETING_SERVER_NAMES='${MARKETING_SERVER_NAMES}'
CODE_CHANGED='${CODE_CHANGED}'
RUNTIME_CHANGED='${RUNTIME_CHANGED}'
CONFIG_CHANGED='${CONFIG_CHANGED}'
NGINX_CONFIG="/etc/nginx/sites-available/\${APP_NAME}.conf"

mkdir -p "\${APP_ROOT}/.trader" "\${APP_DATA}/run" "\${APP_LOG}" "\${REMOTE_DIR}/data"
chown "\${APP_USER}:\${APP_USER}" "\${APP_ROOT}/.trader"
chmod 750 "\${APP_ROOT}/.trader"
chown "\${APP_USER}:\${APP_USER}" "\${APP_DATA}" "\${APP_DATA}/run" "\${APP_LOG}"
chmod 750 "\${APP_DATA}" "\${APP_DATA}/run" "\${APP_LOG}"
chown "\${APP_USER}:\${APP_USER}" "\${REMOTE_DIR}/data"
chmod 750 "\${REMOTE_DIR}/data"
if [ -d "\${REMOTE_DIR}/ui" ]; then
  chown -R root:"\${APP_USER}" "\${REMOTE_DIR}/ui"
  find "\${REMOTE_DIR}/ui" -type d -exec chmod 750 {} +
  find "\${REMOTE_DIR}/ui" -type f -exec chmod 640 {} +
fi

if [ "\${RUNTIME_CHANGED}" = "1" ]; then
rm -rf "\${REMOTE_DIR}/logs" "\${REMOTE_DIR}/.run"
ln -sfn "\${APP_LOG}" "\${REMOTE_DIR}/logs"
ln -sfn "\${APP_DATA}/run" "\${REMOTE_DIR}/.run"

REQUIREMENTS_STAMP="\${APP_ROOT}/.requirements.sha256"
read -r REQUIREMENTS_HASH _ < <(sha256sum "\${REMOTE_DIR}/requirements.txt")
INSTALLED_REQUIREMENTS_HASH="\$(cat "\${REQUIREMENTS_STAMP}" 2>/dev/null || true)"
if [ ! -x "\${APP_ROOT}/venv/bin/python" ]; then
  python3 -m venv "\${APP_ROOT}/venv"
  "\${APP_ROOT}/venv/bin/pip" install --upgrade pip
  INSTALLED_REQUIREMENTS_HASH=""
fi
if [ "\${REQUIREMENTS_HASH}" != "\${INSTALLED_REQUIREMENTS_HASH}" ]; then
  echo "Python bagimliliklari degisti; guncelleniyor..."
  "\${APP_ROOT}/venv/bin/pip" install -r "\${REMOTE_DIR}/requirements.txt"
  printf '%s\n' "\${REQUIREMENTS_HASH}" > "\${REQUIREMENTS_STAMP}"
  chown root:"\${APP_USER}" "\${REQUIREMENTS_STAMP}"
  chmod 640 "\${REQUIREMENTS_STAMP}"
else
  echo "Python bagimliliklari degismedi; kurulum atlandi."
fi

if [ -d "\${REMOTE_DIR}/marketing" ]; then
  mkdir -p "\${MARKETING_ROOT}"
  chown root:root "\${MARKETING_ROOT}"
  chmod 755 "\${MARKETING_ROOT}"
  rsync -rlt --delete --omit-dir-times --no-perms --no-owner --no-group \
    --exclude 'visits.json' "\${REMOTE_DIR}/marketing/" "\${MARKETING_ROOT}/"
  chmod 600 "\${MARKETING_ROOT}/visits.json" 2>/dev/null || true
fi

run_as_app() {
  runuser -u "\${APP_USER}" -- bash -lc "cd '\${REMOTE_DIR}' && set -a && . '\${APP_ENV_FILE}' && set +a && \$*"
}

BACKUP_ROOT="/var/backups/\${APP_NAME}"
BACKUP_STAMP="\$(date +%Y%m%d-%H%M%S)"
mkdir -p "\${BACKUP_ROOT}"
chmod 700 "\${BACKUP_ROOT}"
BACKUP_TMP="\$(mktemp "\${BACKUP_ROOT}/.database-\${BACKUP_STAMP}.XXXXXX.sqlite")"
trap 'rm -f "\${BACKUP_TMP}"' EXIT
python3 - "\${APP_DATA}/tradertrailing.db" "\${BACKUP_TMP}" <<'PY'
import sqlite3
import sys

source_path, backup_path = sys.argv[1:]
source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
target = sqlite3.connect(backup_path)
try:
    source.backup(target)
    result = target.execute("PRAGMA quick_check").fetchone()
    if not result or result[0] != "ok":
        raise RuntimeError(f"Final1 yedek bütünlük denetimi başarısız: {result}")
finally:
    target.close()
    source.close()
PY
gzip -c "\${BACKUP_TMP}" >"\${BACKUP_ROOT}/final1-data-\${BACKUP_STAMP}.sqlite.gz"
chmod 600 "\${BACKUP_ROOT}/final1-data-\${BACKUP_STAMP}.sqlite.gz"
rm -f "\${BACKUP_TMP}"
trap - EXIT
find "\${BACKUP_ROOT}" -maxdepth 1 -type f -name 'final1-data-*.sqlite.gz' -mtime +14 -delete

if [ -f "\${REMOTE_DIR}/alembic.ini" ]; then
  run_as_app "'\${APP_ROOT}/venv/bin/python' -m alembic upgrade head"
else
  echo "Alembic yapilandirmasi yok; SQLAlchemy sema korumasi kullaniliyor."
fi
run_as_app "'\${APP_ROOT}/venv/bin/python' scripts/migrations/migrate_dynamic_mode_v2.py upgrade"
run_as_app "'\${APP_ROOT}/venv/bin/python' scripts/migrations/create_first_admin.py"

systemctl daemon-reload
systemctl restart "\${APP_NAME}-web"
systemctl restart "\${APP_NAME}-worker"
systemctl restart "\${APP_NAME}-manager"
elif [ "\${CONFIG_CHANGED}" = "1" ]; then
  systemctl daemon-reload
  systemctl restart "\${APP_NAME}-web"
  systemctl restart "\${APP_NAME}-worker"
  systemctl restart "\${APP_NAME}-manager"
fi

NGINX_BACKUP="\$(mktemp)"
cp -a "\${NGINX_CONFIG}" "\${NGINX_BACKUP}"
python3 - "\${NGINX_CONFIG}" "\${SERVER_NAMES}" "\${MARKETING_SERVER_NAMES}" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
app_names = sys.argv[2].split()
marketing_names = sys.argv[3].split()
valid_host = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")
if not app_names or not marketing_names:
    raise SystemExit("Nginx domain listesi bos olamaz.")
if any(not valid_host.fullmatch(host) for host in app_names + marketing_names):
    raise SystemExit("Nginx domain listesinde gecersiz alan adi var.")

lines = path.read_text(encoding="utf-8").splitlines()
managed = [
    index
    for index, line in enumerate(lines)
    if line.strip().startswith("server_name ") and line.strip() != "server_name _;"
]
if len(managed) != 4:
    raise SystemExit(f"Beklenen 4 yonetilen server_name satiri bulunamadi: {len(managed)}")
for index in managed[:2]:
    lines[index] = f"  server_name {' '.join(app_names)};"
for index in managed[2:]:
    lines[index] = f"  server_name {' '.join(marketing_names)};"
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
if ! nginx -t; then
  cp -a "\${NGINX_BACKUP}" "\${NGINX_CONFIG}"
  rm -f "\${NGINX_BACKUP}"
  echo "Nginx alan adi guncellemesi geri alindi."
  exit 1
fi
rm -f "\${NGINX_BACKUP}"
systemctl reload nginx

systemctl --no-pager --full status "\${APP_NAME}-web" | sed -n '1,12p'
systemctl --no-pager --full status "\${APP_NAME}-worker" | sed -n '1,10p'
REMOTE

echo ""
echo "Yayin kontrol ediliyor..."
ssh "${SSH_ARGS[@]}" bash <<REMOTE
set -euo pipefail
WEB_PORT='${WEB_PORT}'
PUBLIC_TEST_PORT='${PUBLIC_TEST_PORT}'
SERVER_NAMES='${SERVER_NAMES}'

for i in \$(seq 1 45); do
  if curl -fsS "http://127.0.0.1:\${WEB_PORT}/api/health" >/dev/null 2>&1 && \
     curl -fsS "http://127.0.0.1:\${PUBLIC_TEST_PORT}/api/health" >/dev/null 2>&1; then
    for host in \${SERVER_NAMES}; do
      [ "\${host}" = "_" ] && continue
      curl -fsS -H "Host: \${host}" "http://127.0.0.1/api/health" >/dev/null 2>&1 || true
      break
    done
    echo "Saglik kontrolu basarili."
    exit 0
  fi
  sleep 2
done

echo "HATA: Final1 saglik kontrolu zaman asimina ugradi."
systemctl --no-pager --full status '${APP_NAME}-web' | sed -n '1,30p' || true
journalctl -u '${APP_NAME}-web' -n 80 --no-pager || true
exit 1
REMOTE

echo ""
echo "Origin TLS ve dis dunya erisimi dogrulaniyor..."
PUBLIC_CHECK_FAILED=0
PUBLIC_CHECK_WARNED=0

check_origin_url() {
  local host="$1"
  local path="$2"
  if curl -fsS --max-time 20 \
    --resolve "${host}:443:${SERVER_HOST}" \
    "https://${host}${path}" >/dev/null; then
    echo "  [OK] Origin TLS: ${host}"
  else
    echo "  [HATA] Origin TLS dogrulanamadi: ${host}"
    echo "         Sertifika bu alan adini kapsamiyor olabilir."
    PUBLIC_CHECK_FAILED=1
  fi
}

check_public_url() {
  local host="$1"
  local path="$2"
  local required="${3:-1}"
  if curl -fsSL --max-time 25 --max-redirs 5 \
    "https://${host}${path}" >/dev/null; then
    echo "  [OK] Dis HTTPS: ${host}"
  elif [ "${required}" = "1" ]; then
    echo "  [HATA] Dis HTTPS dogrulanamadi: ${host}"
    PUBLIC_CHECK_FAILED=1
  else
    echo "  [UYARI] Bagimsiz kucuk site dis HTTPS dogrulanamadi: ${host}"
    PUBLIC_CHECK_WARNED=1
  fi
}

for host in ${SERVER_NAMES}; do
  [ "${host}" = "_" ] && continue
  check_origin_url "${host}" "/api/health"
  check_public_url "${host}" "/api/health"
done

for host in ${MARKETING_SERVER_NAMES}; do
  [ "${host}" = "_" ] && continue
  check_origin_url "${host}" "/"
  check_public_url "${host}" "/" 0
done

if [ "${PUBLIC_CHECK_FAILED}" = "1" ]; then
  echo ""
  echo "HATA: Sunucu servisleri calisiyor ancak dis yayin dogrulamasi tamamlanamadi."
  echo "Cloudflare kullanan alanlarda A kaydini ${SERVER_HOST} yapin ve SSL/TLS modunu Full (strict) secin."
  echo "DNS duzeldikten sonra sunucu/ssl-sertifikalarini-guncelle.command dosyasini calistirin."
  exit 1
fi

if [ "${PUBLIC_CHECK_WARNED}" = "1" ]; then
  echo ""
  echo "UYARI: Ana Final1 yayini saglikli; bagimsiz kucuk sitenin Cloudflare dis erisimi ayrica kontrol edilmelidir."
fi

echo ""
echo "Yayin tamamlandi."
echo "Gecici test adresi: http://${SERVER_HOST}:${PUBLIC_TEST_PORT}"
echo "Cloudflare A kaydi IP: ${SERVER_HOST}"
echo "Nginx domainleri: ${SERVER_NAMES}"
echo "Marketing domainleri: ${MARKETING_SERVER_NAMES}"
echo "Marketing klasoru: ${MARKETING_ROOT}"
