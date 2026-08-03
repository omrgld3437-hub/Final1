#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/ortak.sh"

SERVER_NAMES="${SERVER_NAMES:-ayserose.com www.ayserose.com}"
MARKETING_SERVER_NAMES="${MARKETING_SERVER_NAMES:-omeraltin.com www.omeraltin.com}"
LETSENCRYPT_CERT_NAME="${LETSENCRYPT_CERT_NAME:-final1-domains}"
LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-}"

if [ ! -f "$KEY_FILE" ]; then
  printf 'SSH anahtari bulunamadi: %s\n' "$KEY_FILE" >&2
  exit 1
fi

DOMAINS=()
for host in ${SERVER_NAMES} ${MARKETING_SERVER_NAMES}; do
  [ "$host" = "_" ] && continue
  if [[ ! "$host" =~ ^[A-Za-z0-9.-]+$ ]]; then
    printf 'Gecersiz alan adi: %s\n' "$host" >&2
    exit 1
  fi
  DOMAINS+=("$host")
done

if [ "${#DOMAINS[@]}" -eq 0 ]; then
  echo "Sertifikaya eklenecek alan adi yok."
  exit 1
fi

DOMAIN_FLAGS=""
for host in "${DOMAINS[@]}"; do
  printf -v DOMAIN_FLAGS '%s -d %q' "$DOMAIN_FLAGS" "$host"
done

REMOTE_ACCOUNT_EXISTS="$(
  ssh "${SSH_ARGS[@]}" "$(remote_target)" \
    "find /etc/letsencrypt/accounts -name regr.json -type f -print -quit 2>/dev/null | grep -q . && echo yes || echo no"
)"

EMAIL_FLAGS=""
if [ "$REMOTE_ACCOUNT_EXISTS" != "yes" ]; then
  if [ -z "$LETSENCRYPT_EMAIL" ]; then
    echo "Ilk Let's Encrypt kaydi icin LETSENCRYPT_EMAIL ayari gereklidir."
    echo "sunucu/ayarlar.env icine LETSENCRYPT_EMAIL=adresiniz@example.com ekleyin."
    exit 1
  fi
  printf -v EMAIL_FLAGS ' --email %q' "$LETSENCRYPT_EMAIL"
fi

echo "Let's Encrypt sertifikasi tum Final1 alan adlariyla guncelleniyor..."
ssh "${SSH_ARGS[@]}" "$(remote_target)" \
  "certbot certonly --nginx --cert-name $(printf '%q' "$LETSENCRYPT_CERT_NAME") --expand --non-interactive --agree-tos${EMAIL_FLAGS}${DOMAIN_FLAGS} && nginx -t && systemctl reload nginx"

echo ""
echo "Origin sertifikasi ve dis HTTPS dogrulaniyor..."
FAILED=0
for host in "${DOMAINS[@]}"; do
  path="/"
  case " ${SERVER_NAMES} " in
    *" ${host} "*) path="/api/health" ;;
  esac
  if curl -fsS --max-time 20 \
    --resolve "${host}:443:${SERVER_HOST}" \
    "https://${host}${path}" >/dev/null; then
    echo "  [OK] Origin TLS: ${host}"
  else
    echo "  [HATA] Origin TLS: ${host}"
    FAILED=1
  fi
  if curl -fsSL --max-time 25 --max-redirs 5 \
    "https://${host}${path}" >/dev/null; then
    echo "  [OK] Dis HTTPS: ${host}"
  else
    echo "  [HATA] Dis HTTPS: ${host}"
    FAILED=1
  fi
done

if [ "$FAILED" = "1" ]; then
  echo "Sertifika islemi tamamlandi ancak en az bir dis alan adi dogrulanamadi."
  echo "Cloudflare A kayitlarini ve SSL/TLS Full (strict) modunu kontrol edin."
  exit 1
fi

echo "SSL sertifikasi ve Nginx basariyla guncellendi."
