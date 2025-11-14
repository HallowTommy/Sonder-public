#!/usr/bin/env bash
set -Eeuo pipefail

# ===== Настройки (можно переопределять через переменные окружения) =====
PROJECT_DIR="${PROJECT_DIR:-/opt/Sonder}"
PS_SCRIPT_REL="${PS_SCRIPT_REL:-scripts/local_full_backup.ps1}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
HOST_MEDIA_PATH="${HOST_MEDIA_PATH:-/opt/Sonder/media}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
BACKUPS_ROOT="${BACKUPS_ROOT:-/root/Downloads/SonderBackups}"

# Папка, которую раздаёт Caddy
PUBLISH_DIR="${PUBLISH_DIR:-/var/www/sonder-backups}"

# Базовый URL (для ссылки)
BASE_URL="${BASE_URL:-https://sonderhomefeeling.com}"

# Через сколько минут удалить опубликованный архив
TTL_MIN="${TTL_MIN:-60}"

# Делать новый бэкап (1) или брать последний (0)
DO_BACKUP="${DO_BACKUP:-1}"

# Удалять исходную папку бэкапа после упаковки (1/0)
REMOVE_SOURCE="${REMOVE_SOURCE:-1}"

# ===== Проверки =====
command -v pwsh >/dev/null || { echo "pwsh not found. Install PowerShell 7."; exit 1; }

# ===== Подготовка publish-dir (делаем и правим права) =====
if ! mkdir -p "$PUBLISH_DIR" 2>/dev/null; then
  echo ">> mkdir requires sudo for $PUBLISH_DIR"
  sudo mkdir -p "$PUBLISH_DIR"
fi
if ! chown root:root "$PUBLISH_DIR" 2>/dev/null; then
  echo ">> chown requires sudo for $PUBLISH_DIR"
  sudo chown root:root "$PUBLISH_DIR"
fi
if ! chmod 755 "$PUBLISH_DIR" 2>/dev/null; then
  echo ">> chmod requires sudo for $PUBLISH_DIR"
  sudo chmod 755 "$PUBLISH_DIR"
fi

cd "$PROJECT_DIR"

# ===== 1) (опционально) создаём свежий бэкап =====
if [[ "$DO_BACKUP" -eq 1 ]]; then
  echo ">> Creating fresh backup via PowerShell..."
  pwsh -NoProfile -File "$PS_SCRIPT_REL" \
    -Action Backup \
    -RetentionDays "$RETENTION_DAYS" \
    -ComposeFile "$COMPOSE_FILE" \
    -HostMediaPath "$HOST_MEDIA_PATH"
fi

# ===== 2) Находим самую свежую папку бэкапа =====
echo ">> Resolving latest backup under $BACKUPS_ROOT ..."
LATEST="$(ls -1dt "$BACKUPS_ROOT"/* 2>/dev/null | head -n1 || true)"
[[ -n "$LATEST" ]] || { echo "No backups in $BACKUPS_ROOT"; exit 1; }
echo ">> Latest: $LATEST"

# ===== 3) Упаковка в единый архив =====
STAMP="$(date +%Y-%m-%d_%H-%M)"
RAND="$(head -c8 /dev/urandom | xxd -p)"
ARCHIVE="sonder_full_${STAMP}_${RAND}.tar.gz"

echo ">> Packing into: $PUBLISH_DIR/$ARCHIVE"
tar -C "$LATEST" -czf "$PUBLISH_DIR/$ARCHIVE" .

if [[ "$REMOVE_SOURCE" -eq 1 ]]; then
  echo ">> Removing source folder: $LATEST"
  rm -rf --one-file-system "$LATEST"
fi

# ===== 4) Печатаем ссылку и ставим автоудаление =====
URL="${BASE_URL%/}/backups/${ARCHIVE}"

cat <<MSG

=======================================
Скачай бэкап по ссылке (удалится через ~${TTL_MIN} мин):
$URL

или через curl:
curl -O "$URL"
=======================================
MSG

( sleep $((TTL_MIN*60)); rm -f "$PUBLISH_DIR/$ARCHIVE" ) >/dev/null 2>&1 &
echo ">> Scheduled cleanup of $ARCHIVE in $TTL_MIN minutes."
