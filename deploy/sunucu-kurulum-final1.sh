#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-final1}"
APP_USER="${APP_USER:-final1app}"
APP_ROOT="${APP_ROOT:-/opt/${APP_NAME}}"
APP_DIR="${APP_ROOT}/current"
APP_DATA="${APP_DATA:-/var/lib/${APP_NAME}}"
APP_LOG="${APP_LOG:-/var/log/${APP_NAME}}"
APP_ENV_DIR="${APP_ENV_DIR:-/etc/${APP_NAME}}"
APP_ENV_FILE="${APP_ENV_FILE:-${APP_ENV_DIR}/${APP_NAME}.env}"
MARKETING_ROOT="${MARKETING_ROOT:-/var/www/${APP_NAME}-marketing}"
APP_TLS_DIR="${APP_TLS_DIR:-${APP_ENV_DIR}/tls}"
APP_TLS_CERT="${APP_TLS_CERT:-${APP_TLS_DIR}/${APP_NAME}.origin.crt}"
APP_TLS_KEY="${APP_TLS_KEY:-${APP_TLS_DIR}/${APP_NAME}.origin.key}"
LETSENCRYPT_CERT_NAME="${LETSENCRYPT_CERT_NAME:-final1-domains}"
WEB_PORT="${WEB_PORT:-8000}"
MANAGER_PORT="${MANAGER_PORT:-7999}"
PUBLIC_TEST_PORT="${PUBLIC_TEST_PORT:-8081}"
SSH_PORT="${SSH_PORT:-22666}"
SERVER_NAMES="${SERVER_NAMES:-ayserose.com www.ayserose.com}"
MARKETING_SERVER_NAMES="${MARKETING_SERVER_NAMES:-omeraltin.com www.omeraltin.com}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Bu kurulum dosyasi sunucuda root olarak calistirilmelidir."
  exit 1
fi

echo "Paketler hazirlaniyor..."
apt-get update
apt-get install -y \
  build-essential \
  ca-certificates \
  certbot \
  curl \
  fail2ban \
  nginx \
  python3-certbot-nginx \
  python3-pip \
  python3-venv \
  rsync \
  sqlite3 \
  ufw

if ! id "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --home "${APP_ROOT}" --shell /usr/sbin/nologin "${APP_USER}"
fi

mkdir -p "${APP_DIR}" "${APP_ROOT}/.trader" "${APP_DATA}/run" "${APP_LOG}" "${APP_ENV_DIR}" "${APP_TLS_DIR}" "${MARKETING_ROOT}" /var/www/letsencrypt/.well-known/acme-challenge
chown -R root:"${APP_USER}" "${APP_ROOT}"
chmod 750 "${APP_ROOT}" "${APP_DIR}"
chown -R "${APP_USER}:${APP_USER}" "${APP_ROOT}/.trader"
chmod 750 "${APP_ROOT}/.trader"
chown -R "${APP_USER}:${APP_USER}" "${APP_DATA}" "${APP_LOG}"
chmod 750 "${APP_DATA}" "${APP_DATA}/run" "${APP_LOG}"
for _log_dir in "Kullanıcı Logları" "Sistem Logları"; do
  mkdir -p "${APP_DIR}/${_log_dir}"
  chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}/${_log_dir}"
  chmod 2770 "${APP_DIR}/${_log_dir}"
done

if [ ! -f "${APP_ENV_FILE}" ]; then
  MASTER_KEY="$(openssl rand -base64 48 | tr -d '\n')"
  cat > "${APP_ENV_FILE}" <<ENV
FINAL1_ENV_PLACEHOLDER=1
APP_ENV=production
DATABASE_URL=sqlite:////var/lib/${APP_NAME}/tradertrailing.db
BINANCE_MASTER_KEY=${MASTER_KEY}
WEB_INTERNAL_URL=http://127.0.0.1:${WEB_PORT}
ALLOWED_ORIGINS=
AUTH_COOKIE_SECURE_AUTO=1
AUTH_COOKIE_SECURE=1
SESSION_TTL_DAYS=3650
AUTH_COOKIE_MAX_AGE_SEC=315360000
AUTH_SLIDING_TTL=1
SECURITY_HEADERS_ENABLED=1
CSP_ENABLED=1
CSP_REPORT_ONLY=1
HSTS_ENABLED=1
WEB_UVICORN_WORKERS=2
PARAM_POOL_WARMUP=0
BINANCE_USER_STREAM_ENABLED=1
ENV
fi
chown root:"${APP_USER}" "${APP_ENV_FILE}"
chmod 640 "${APP_ENV_FILE}"

FIRST_SERVER_NAME=""
SAN_LIST=""
for host in ${SERVER_NAMES} ${MARKETING_SERVER_NAMES}; do
  [ "${host}" = "_" ] && continue
  [ -z "${FIRST_SERVER_NAME}" ] && FIRST_SERVER_NAME="${host}"
  if [ -z "${SAN_LIST}" ]; then
    SAN_LIST="DNS:${host}"
  else
    SAN_LIST="${SAN_LIST},DNS:${host}"
  fi
done
[ -z "${FIRST_SERVER_NAME}" ] && FIRST_SERVER_NAME="${APP_NAME}.local"
[ -z "${SAN_LIST}" ] && SAN_LIST="DNS:${FIRST_SERVER_NAME}"

if [ ! -s "${APP_TLS_CERT}" ] || [ ! -s "${APP_TLS_KEY}" ]; then
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
    -keyout "${APP_TLS_KEY}" \
    -out "${APP_TLS_CERT}" \
    -subj "/CN=${FIRST_SERVER_NAME}" \
    -addext "subjectAltName=${SAN_LIST}" \
    >/dev/null 2>&1
fi
chown root:root "${APP_TLS_CERT}" "${APP_TLS_KEY}"
chmod 644 "${APP_TLS_CERT}"
chmod 600 "${APP_TLS_KEY}"
chmod 700 "${APP_TLS_DIR}"

NGINX_SSL_CERT="${APP_TLS_CERT}"
NGINX_SSL_KEY="${APP_TLS_KEY}"
LETSENCRYPT_LIVE_DIR="/etc/letsencrypt/live/${LETSENCRYPT_CERT_NAME}"
if [ -s "${LETSENCRYPT_LIVE_DIR}/fullchain.pem" ] && [ -s "${LETSENCRYPT_LIVE_DIR}/privkey.pem" ]; then
  NGINX_SSL_CERT="${LETSENCRYPT_LIVE_DIR}/fullchain.pem"
  NGINX_SSL_KEY="${LETSENCRYPT_LIVE_DIR}/privkey.pem"
fi

cat > "/etc/systemd/system/${APP_NAME}-web.service" <<SERVICE
[Unit]
Description=Final1 FastAPI web service
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_ENV_FILE}
Environment=DATABASE_ROLE=web
Environment=PROCESS_ROLE=api
ExecStart=${APP_ROOT}/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port ${WEB_PORT} --workers 2 --loop uvloop --http httptools --log-level warning --no-access-log
Restart=always
RestartSec=3
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ProtectClock=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
PrivateDevices=true
RestrictSUIDSGID=true
LockPersonality=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadWritePaths=${APP_DATA} ${APP_LOG} ${APP_DIR}/data ${APP_ROOT}/.trader

[Install]
WantedBy=multi-user.target
SERVICE

cat > "/etc/systemd/system/${APP_NAME}-worker.service" <<SERVICE
[Unit]
Description=Final1 bot engine worker
After=network.target ${APP_NAME}-web.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_ENV_FILE}
Environment=DATABASE_ROLE=worker
Environment=PROCESS_ROLE=worker
ExecStart=${APP_ROOT}/venv/bin/python -m app.botengine.worker_main
Restart=always
RestartSec=3
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ProtectClock=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
PrivateDevices=true
RestrictSUIDSGID=true
LockPersonality=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadWritePaths=${APP_DATA} ${APP_LOG} ${APP_DIR}/data ${APP_ROOT}/.trader

[Install]
WantedBy=multi-user.target
SERVICE

cat > "/etc/systemd/system/${APP_NAME}-manager.service" <<SERVICE
[Unit]
Description=Final1 local manager service
After=network.target ${APP_NAME}-web.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_ENV_FILE}
Environment=MANAGER_PORT=${MANAGER_PORT}
ExecStart=${APP_ROOT}/venv/bin/python -m manager_server
Restart=always
RestartSec=3
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ProtectClock=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
PrivateDevices=true
RestrictSUIDSGID=true
LockPersonality=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadWritePaths=${APP_DATA} ${APP_LOG} ${APP_DIR}/data ${APP_ROOT}/.trader

[Install]
WantedBy=multi-user.target
SERVICE

cat > "/etc/nginx/sites-available/${APP_NAME}.conf" <<NGINX
server {
  listen 80;
  listen [::]:80;
  server_name ${SERVER_NAMES};

  access_log /var/log/nginx/${APP_NAME}.access.log;
  error_log /var/log/nginx/${APP_NAME}.error.log warn;

  server_tokens off;

  add_header X-Frame-Options "DENY" always;
  add_header X-Content-Type-Options "nosniff" always;
  add_header Referrer-Policy "same-origin" always;
  add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;

  location ^~ /.well-known/acme-challenge/ {
    root /var/www/letsencrypt;
    default_type "text/plain";
    try_files \$uri =404;
  }

  location / {
    return 301 https://\$host\$request_uri;
  }
}

server {
  listen 443 ssl http2;
  listen [::]:443 ssl http2;
  server_name ${SERVER_NAMES};

  ssl_certificate ${NGINX_SSL_CERT};
  ssl_certificate_key ${NGINX_SSL_KEY};
  ssl_protocols TLSv1.2 TLSv1.3;
  ssl_session_cache shared:${APP_NAME}_ssl:10m;
  ssl_session_timeout 1d;

  access_log /var/log/nginx/${APP_NAME}-ssl.access.log;
  error_log /var/log/nginx/${APP_NAME}-ssl.error.log warn;

  client_max_body_size 20m;
  server_tokens off;

  add_header X-Frame-Options "DENY" always;
  add_header X-Content-Type-Options "nosniff" always;
  add_header Referrer-Policy "same-origin" always;
  add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;

  location ~ /\.(?!well-known) {
    return 404;
  }

  location / {
    proxy_pass http://127.0.0.1:${WEB_PORT};
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 1h;
    proxy_send_timeout 1h;
  }
}

server {
  listen 80;
  listen [::]:80;
  server_name ${MARKETING_SERVER_NAMES};
  access_log /var/log/nginx/${APP_NAME}-marketing.access.log;
  error_log /var/log/nginx/${APP_NAME}-marketing.error.log warn;

  server_tokens off;

  add_header X-Frame-Options "DENY" always;
  add_header X-Content-Type-Options "nosniff" always;
  add_header Referrer-Policy "same-origin" always;
  add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;

  location ^~ /.well-known/acme-challenge/ {
    root /var/www/letsencrypt;
    default_type "text/plain";
    try_files \$uri =404;
  }

  location / {
    return 301 https://\$host\$request_uri;
  }
}

server {
  listen 443 ssl http2;
  listen [::]:443 ssl http2;
  server_name ${MARKETING_SERVER_NAMES};
  root ${MARKETING_ROOT};
  index index.html;

  ssl_certificate ${NGINX_SSL_CERT};
  ssl_certificate_key ${NGINX_SSL_KEY};
  ssl_protocols TLSv1.2 TLSv1.3;
  ssl_session_cache shared:${APP_NAME}_marketing_ssl:10m;
  ssl_session_timeout 1d;

  access_log /var/log/nginx/${APP_NAME}-marketing-ssl.access.log;
  error_log /var/log/nginx/${APP_NAME}-marketing-ssl.error.log warn;

  server_tokens off;

  add_header X-Frame-Options "DENY" always;
  add_header X-Content-Type-Options "nosniff" always;
  add_header Referrer-Policy "same-origin" always;
  add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;

  location = /visits.json {
    return 404;
  }

  location ^~ /api/ {
    return 404;
  }

  location ^~ /ui/ {
    return 404;
  }

  location ~ /\.(?!well-known) {
    return 404;
  }

  location / {
    try_files \$uri \$uri/ /index.html;
  }
}

server {
  listen ${PUBLIC_TEST_PORT} default_server;
  listen [::]:${PUBLIC_TEST_PORT} default_server;
  server_name _;

  access_log /var/log/nginx/${APP_NAME}-${PUBLIC_TEST_PORT}.access.log;
  error_log /var/log/nginx/${APP_NAME}-${PUBLIC_TEST_PORT}.error.log warn;

  client_max_body_size 20m;
  server_tokens off;

  location / {
    proxy_pass http://127.0.0.1:${WEB_PORT};
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 1h;
    proxy_send_timeout 1h;
  }
}
NGINX

ln -sfn "/etc/nginx/sites-available/${APP_NAME}.conf" "/etc/nginx/sites-enabled/${APP_NAME}.conf"

install -d -o root -g root -m 755 /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
nginx -t
systemctl reload nginx
HOOK
chown root:root /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
chmod 750 /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

nginx -t
systemctl daemon-reload
systemctl enable "${APP_NAME}-web" "${APP_NAME}-worker" "${APP_NAME}-manager"
systemctl enable nginx
systemctl enable --now certbot.timer >/dev/null 2>&1 || true
systemctl restart nginx

ufw allow "${SSH_PORT}/tcp"
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow "${PUBLIC_TEST_PORT}/tcp"
ufw --force enable

echo
echo "Kurulum tamamlandi."
echo "Uygulama dizini: ${APP_DIR}"
echo "Env dosyasi: ${APP_ENV_FILE}"
echo "Nginx domainleri: ${SERVER_NAMES}"
echo "Marketing domainleri: ${MARKETING_SERVER_NAMES}"
echo "Marketing klasoru: ${MARKETING_ROOT}"
echo "Gecici test adresi: http://SUNUCU_IP:${PUBLIC_TEST_PORT}"
