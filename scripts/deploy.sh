#!/usr/bin/env bash
set -Eeuo pipefail

# ===============================
# Настройки (меняй при необходимости)
# ===============================
APP_DIR="${APP_DIR:-/opt/Sonder}"
BRANCH="${BRANCH:-main}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
DJ_SERVICE="${DJ_SERVICE:-web}"
CADDY_SERVICE="${CADDY_SERVICE:-caddy}"

# Если веб-образы в GHCR и нужен логин:
GHCR_USER="${GHCR_USER:-$USER}"
GHCR_TOKEN="${GHCR_TOKEN:-}"

# Поддержка: ./deploy.sh <IMAGE_TAG_OR_SHA>
if [[ -n "${1:-}" ]]; then VERSION="$1"; fi
VERSION="${VERSION:-latest}"

log(){  echo -e "\033[1;36m$1\033[0m"; }
ok(){   echo -e "\033[1;32m$1\033[0m"; }
warn(){ echo -e "\033[1;33m$1\033[0m"; }

trap 'warn "❌ Ошибка деплоя на строке $LINENO"; exit 1' ERR

cd "$APP_DIR"

# ===============================
# 1) Код
# ===============================
log "[1/9] Git: fetch + hard reset → origin/${BRANCH}"
git fetch --all
git checkout -q "${BRANCH}"
git reset --hard "origin/${BRANCH}"

# ===============================
# 2) Логин в реестр (если нужен)
# ===============================
if [[ -n "$GHCR_TOKEN" ]]; then
  log "[2/9] Docker: login GHCR как ${GHCR_USER}"
  echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin || true
else
  log "[2/9] Docker: login пропущен (public/уже залогинен)"
fi

# ===============================
# 3) Тянем образ(ы)
# ===============================
log "[3/9] Docker: pull $DJ_SERVICE (VERSION=${VERSION})"
VERSION="$VERSION" docker compose -f "$COMPOSE_FILE" pull "$DJ_SERVICE" || true

# ===============================
# 4) Поднимаем контейнер приложения
# ===============================
log "[4/9] Docker: up --force-recreate (no-deps) для $DJ_SERVICE"
VERSION="$VERSION" docker compose -f "$COMPOSE_FILE" up -d --force-recreate --no-deps "$DJ_SERVICE"

# ===============================
# 5) Применяем миграции
# ===============================
log "[5/9] Django: migrate"
docker compose -f "$COMPOSE_FILE" exec -T "$DJ_SERVICE" \
  python manage.py migrate --noinput

# ===============================
# 6) Собираем статику
# ===============================
log "[6/9] Django: collectstatic"
docker compose -f "$COMPOSE_FILE" exec -T "$DJ_SERVICE" \
  python manage.py collectstatic --noinput || true

# ===============================
# 7) Чистим .pyc и рестартим web
# ===============================
log "[7/9] Cleanup .pyc + restart $DJ_SERVICE"
docker compose -f "$COMPOSE_FILE" exec -T "$DJ_SERVICE" bash -lc "find /app -name '*.pyc' -delete" || true
docker compose -f "$COMPOSE_FILE" restart "$DJ_SERVICE"

# ===============================
# 8) Перегружаем Caddy (если есть)
# ===============================
if docker compose -f "$COMPOSE_FILE" ps | grep -q "$CADDY_SERVICE"; then
  log "[8/9] Caddy: reload конфигурации"
  docker compose -f "$COMPOSE_FILE" exec -T "$CADDY_SERVICE" \
    caddy reload --config /etc/caddy/Caddyfile || \
  docker compose -f "$COMPOSE_FILE" restart "$CADDY_SERVICE"
else
  log "[8/9] Caddy: сервис не найден → пропуск"
fi

# ===============================
# 9) Sanity-check
# ===============================
log "[9/9] Sanity-check (Django init + admin hook)"
docker compose -f "$COMPOSE_FILE" exec -T "$DJ_SERVICE" python - <<'PY' || true
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
django.setup()
from shop.admin import ProductPhotoAdmin
print("has_module_permission:", hasattr(ProductPhotoAdmin, 'has_module_permission'))
print("get_model_perms:", hasattr(ProductPhotoAdmin, 'get_model_perms'))
PY

ok "✓ Deploy завершён: $(date)"
