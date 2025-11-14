param(
  [ValidateSet('Backup','Restore')]
  [string]$Action = 'Backup',

  # docker-compose
  [string]$ComposeFile = 'docker-compose.yml',
  [string]$DbService   = 'db',
  [string]$WebService  = 'web',

  # media
  [string]$MediaInContainer = '/app/media',
  [string]$HostMediaPath    = (Join-Path (Get-Location) 'media'),

  # retention (0 — не удалять)
  [int]$RetentionDays = 0,

  # явный выбор файлов при Restore (опционально)
  [string]$DumpPath = '',
  [string]$MediaZipPath = ''
)

$ErrorActionPreference = 'Stop'
function Ensure-Dir($p){ New-Item -ItemType Directory -Force -Path $p | Out-Null }
function NowStamp { Get-Date -Format 'yyyy-MM-dd_HH-mm' }

# --------- пути бэкапов ----------
$downloads   = [Environment]::GetFolderPath('UserProfile') + '\Downloads'
$backupsRoot = Join-Path $downloads 'SonderBackups'
Ensure-Dir $backupsRoot

# --------- утилиты ----------
function Dc-StopQuiet($service){ cmd /c "docker compose -f `"$ComposeFile`" stop $service 1>nul 2>nul" }
function Dc-StartQuiet($service){ cmd /c "docker compose -f `"$ComposeFile`" start $service 1>nul 2>nul" }
function Dc-UpIfMissing([string[]]$services){
  $ps = (docker compose -f $ComposeFile ps --services 2>$null) -join ' '
  foreach($s in $services){
    if (-not $ps.Contains($s)){
      Write-Host ">> Bringing up: $($services -join ', ')"
      cmd /c "docker compose -f `"$ComposeFile`" up -d $($services -join ' ')"
      break
    }
  }
}
function Wait-PostgresReady($timeoutSec=60){
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  do{
    $ok = $false
    try{
      docker compose -f $ComposeFile exec -T $DbService sh -lc "pg_isready -h 127.0.0.1 -p 5432" | Out-Null
      if ($LASTEXITCODE -eq 0){ $ok = $true }
    } catch {}
    if ($ok){ return }
    Start-Sleep -Seconds 2
  } while((Get-Date) -lt $deadline)
  throw "Postgres is not ready after $timeoutSec s"
}

# --------- гарантированно получить параметры БД ----------
Dc-UpIfMissing @($DbService)
Wait-PostgresReady

$PGDB  = (docker compose -f $ComposeFile exec -T $DbService printenv POSTGRES_DB).Trim()
$PGUSR = (docker compose -f $ComposeFile exec -T $DbService printenv POSTGRES_USER).Trim()
$PGPWD = (docker compose -f $ComposeFile exec -T $DbService printenv POSTGRES_PASSWORD).Trim()
if (-not $PGDB)  { $PGDB  = 'sonder_db' }
if (-not $PGUSR) { $PGUSR = 'sonder_user' }

Write-Host ">> ACTION=$Action DB=$PGDB USER=$PGUSR SERVICES: db=$DbService web=$WebService"
Write-Host ">> Backup folder: $backupsDir"

# ===================== BACKUP =====================
if ($Action -eq 'Backup') {
  $dayFolder  = NowStamp
  $backupsDir = Join-Path $backupsRoot $dayFolder
  Ensure-Dir $backupsDir
  Write-Host ">> Backup folder: $backupsDir"

  # ---- DB: pg_dump -> .dump ----
  $dumpName   = "$PGDB" + '_' + $stamp + '.dump'
  $dumpHost   = Join-Path $backupsDir $dumpName
  $dumpInCont = "/tmp/$dumpName"

  Write-Host ">> Creating DB dump: $dumpInCont"
  $dumpCmd = "PGPASSWORD=`"$PGPWD`" pg_dump -h 127.0.0.1 -U `"$PGUSR`" -d `"$PGDB`" -F c -f `"$dumpInCont`""
  docker compose -f $ComposeFile exec -T $DbService sh -lc $dumpCmd
  if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed' }

  # проверка размера
  $sizeInCont = docker compose -f $ComposeFile exec -T $DbService sh -lc "stat -c%s $dumpInCont 2>/dev/null || wc -c $dumpInCont"
  if (-not $sizeInCont -or [int64]$sizeInCont -le 0) {
    docker compose -f $ComposeFile exec -T $DbService sh -lc "rm -f $dumpInCont" | Out-Null
    throw 'Backup file in container is empty - abort'
  }

  docker compose -f $ComposeFile cp "$($DbService):$dumpInCont" "$dumpHost"
  docker compose -f $ComposeFile exec -T $DbService sh -lc "rm -f $dumpInCont"

  # ---- MEDIA: zip ----
  $mediaZip = Join-Path $backupsDir ("media_" + $stamp + ".zip")
  if (Test-Path $HostMediaPath) {
    Write-Host ">> Zipping host media: $HostMediaPath"
    if (Test-Path $mediaZip) { Remove-Item -Force $mediaZip }
    Compress-Archive -Path (Join-Path $HostMediaPath '*') -DestinationPath $mediaZip -Force
  } else {
    Write-Host ">> Copying media from container: $($WebService):$MediaInContainer"
    Dc-UpIfMissing @($WebService)
    $tmpDir = Join-Path $env:TEMP ("sonder_media_" + $stamp)
    Ensure-Dir $tmpDir
    docker compose -f $ComposeFile cp "$($WebService):$MediaInContainer" (Join-Path $tmpDir 'media')
    $src = Join-Path $tmpDir 'media'
    if (-not (Test-Path $src)) { throw 'No media copied from container' }
    if (Test-Path $mediaZip) { Remove-Item -Force $mediaZip }
    Compress-Archive -Path (Join-Path $src '*') -DestinationPath $mediaZip -Force
    Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
  }

  # ---- Ротация ----
  if ($RetentionDays -gt 0) {
    Write-Host ">> Retention: $RetentionDays days (delete old dated folders)"
    Get-ChildItem $backupsRoot -Directory |
      Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$RetentionDays) } |
      Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
  }

  # ---- Манифест ----
  $manifest = Join-Path $backupsDir ("manifest_" + $stamp + ".txt")
  @(
    "Sonder Full Backup",
    "Timestamp: $stamp",
    "Folder: $backupsDir",
    "DB dump: $dumpHost",
    "Media zip: $mediaZip"
  ) | Set-Content -Path $manifest -Encoding UTF8

  Write-Host "OK: full backup created"
  Write-Host " - DB: $dumpHost"
  Write-Host " - media: $mediaZip"
  Write-Host " - manifest: $manifest"
  exit 0
}

# ===================== RESTORE =====================
if ($Action -eq 'Restore') {
  Dc-UpIfMissing @($DbService,$WebService)
  Wait-PostgresReady

  # выбрать свежие файлы, если пути не заданы
  if (-not $DumpPath -or -not (Test-Path $DumpPath)) {
    $DumpPath = Get-ChildItem $backupsRoot -Recurse -Filter '*.dump' |
      Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object { $_.FullName }
  }
  if (-not $MediaZipPath -or -not (Test-Path $MediaZipPath)) {
    $MediaZipPath = Get-ChildItem $backupsRoot -Recurse -Filter 'media_*.zip' |
      Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object { $_.FullName }
  }
  if (-not (Test-Path $DumpPath)) { throw "Dump file not found: $DumpPath" }

  # ---- DB: полная замена ----
  $dumpName   = [IO.Path]::GetFileName($DumpPath)
  $dumpInCont = "/tmp/$dumpName"
  Write-Host ">> Uploading DB dump: $dumpName"
  docker compose -f $ComposeFile cp $DumpPath "$($DbService):$dumpInCont"

  Write-Host ">> Stopping web (optional)"
  Dc-StopQuiet $WebService

  Write-Host ">> Recreate DB: $PGDB"
  docker compose -f $ComposeFile exec -T $DbService psql -U $PGUSR -d postgres -v "ON_ERROR_STOP=1" -c "DROP DATABASE IF EXISTS $PGDB WITH (FORCE);"
  docker compose -f $ComposeFile exec -T $DbService psql -U $PGUSR -d postgres -v "ON_ERROR_STOP=1" -c "CREATE DATABASE $PGDB OWNER $PGUSR;"

# ---- EXTENSIONS (до pg_restore) ----
Write-Host ">> Ensure minimal extensions (safe)"
$extCmds = @(
  "CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;"
)
foreach($sql in $extCmds){
  docker compose -f $ComposeFile exec -T $DbService `
    psql -U $PGUSR -d $PGDB -v ON_ERROR_STOP=1 -c $sql
}

# ---- Восстановление ----
Write-Host ">> Restoring DB (full, verbose)"
$restoreCmd = "PGPASSWORD=`"$PGPWD`" pg_restore -v -h 127.0.0.1 -U `"$PGUSR`" -d `"$PGDB`" -1 --clean --if-exists --no-owner --no-privileges --role=`"$PGUSR`" `"$dumpInCont`""
docker compose -f $ComposeFile exec -T $DbService sh -lc $restoreCmd
if ($LASTEXITCODE -ne 0) { throw 'pg_restore failed' }
docker compose -f $ComposeFile exec -T $DbService sh -lc "rm -f $dumpInCont"


  # ---- Быстрые проверки ----
  Write-Host ">> Sanity checks"
  docker compose -f $ComposeFile exec -T $DbService psql -U $PGUSR -d $PGDB -v ON_ERROR_STOP=1 -c "select count(*) as users from auth_user;"       | Out-Host
  docker compose -f $ComposeFile exec -T $DbService psql -U $PGUSR -d $PGDB -v ON_ERROR_STOP=1 -c "select count(*) as products from shop_product;" | Out-Host
  docker compose -f $ComposeFile exec -T $DbService psql -U $PGUSR -d $PGDB -v ON_ERROR_STOP=1 -c "select count(*) as orders from shop_order;"     | Out-Host

  # ---- MEDIA: распаковать на хост и скопировать в контейнер ----
  if ($MediaZipPath -and (Test-Path $MediaZipPath)) {
    Write-Host ">> Restoring media to host: $HostMediaPath"
    if (Test-Path $HostMediaPath) {
      Get-ChildItem $HostMediaPath -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    } else {
      Ensure-Dir $HostMediaPath
    }
    Expand-Archive -Path $MediaZipPath -DestinationPath $HostMediaPath -Force

    Write-Host ">> Sync media into container: $MediaInContainer"
    $tmp = Join-Path $env:TEMP "sonder_media_restore"
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    Ensure-Dir $tmp
    Copy-Item -Recurse -Force (Join-Path $HostMediaPath '*') $tmp
    docker compose -f $ComposeFile exec -T $WebService sh -lc "mkdir -p `"$MediaInContainer`" && rm -rf `"$MediaInContainer/*`" 2>/dev/null || true"
    docker compose -f $ComposeFile cp "$tmp\." "$($WebService):$MediaInContainer"
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue

    Write-Host ">> Starting web (for media normalization)"
Dc-StartQuiet $WebService
Start-Sleep -Seconds 2

Write-Host ">> Normalize media paths (FS & DB)"

# --- Файловая структура внутри контейнера web ---
# Если архив развернулся как /app/media/media/* -> переместить уровнем выше
docker compose -f $ComposeFile exec -T $WebService sh -lc "
  set -e
  MEDIA='$MediaInContainer'
  [ -d \"\$MEDIA/media\" ] && { shopt -s dotglob 2>/dev/null || true; mv \"\$MEDIA/media\"/* \"\$MEDIA/\" && rmdir \"\$MEDIA/media\"; } || true
  mkdir -p \"\$MEDIA/products/photos\" \"\$MEDIA/banners\" \"\$MEDIA/homepage\"
"

# --- Починить пути в БД (если вдруг со 'media/' префиксом) ---
docker compose -f $ComposeFile exec -T $DbService `
  psql -U $PGUSR -d $PGDB -c "UPDATE shop_product SET image = regexp_replace(image, '^media/','') WHERE image LIKE 'media/%';"

docker compose -f $ComposeFile exec -T $DbService `
  psql -U $PGUSR -d $PGDB -c "UPDATE easy_thumbnails_source SET name = regexp_replace(name, '^media/','') WHERE name LIKE 'media/%';"

# --- Быстрые sanity-проверки ---
docker compose -f $ComposeFile exec -T $DbService `
  psql -U $PGUSR -d $PGDB -c "SELECT image FROM shop_product WHERE image IS NOT NULL LIMIT 5;"

docker compose -f $ComposeFile exec -T $WebService sh -lc "
  find '$MediaInContainer' -maxdepth 2 -type f | head -n 10
"


    # ---------- MEDIA PATH NORMALIZATION ----------
    Write-Host ">> Normalize media paths (FS & DB)"
    # 1) если распаковалось как /app/media/media/* — поднимем на уровень выше
    docker compose -f $ComposeFile exec -T $WebService sh -lc "[ -d `"$MediaInContainer/media`" ] && mv `"$MediaInContainer/media/*`" `"$MediaInContainer/`" && rmdir `"$MediaInContainer/media`" || true"

    # 2) посчитаем количество файлов на ФС
    $cntFsPhotos = (docker compose -f $ComposeFile exec -T $WebService sh -lc "[ -d `"$MediaInContainer/products/photos`" ] && find `"$MediaInContainer/products/photos`" -type f | wc -l || echo 0").Trim()
    $cntFsFlat   = (docker compose -f $ComposeFile exec -T $WebService sh -lc "find `"$MediaInContainer/products`" -maxdepth 1 -type f | wc -l").Trim()

    # 3) приведём БД: сперва уберём возможный префикс 'media/'
    docker compose -f $ComposeFile exec -T $DbService psql -U $PGUSR -d $PGDB -c "update shop_product set image = regexp_replace(image, '^media/','') where image like 'media/%';" | Out-Null
    docker compose -f $ComposeFile exec -T $DbService psql -U $PGUSR -d $PGDB -c "update easy_thumbnails_source set name = regexp_replace(name, '^media/','') where name like 'media/%';" | Out-Null

    # 4) определим канонику по ФС
    $usePhotos = ([int]$cntFsPhotos -ge [int]$cntFsFlat)

    if ($usePhotos) {
      Write-Host ">> Canonical layout: products/photos/ (files in /products/photos: $cntFsPhotos)"
      # правим БД — добавляем photos/, где его нет
      docker compose -f $ComposeFile exec -T $DbService psql -U $PGUSR -d $PGDB -c "update shop_product set image = regexp_replace(image, '^products/', 'products/photos/') where image like 'products/%' and image not like 'products/photos/%';" | Out-Null
      docker compose -f $ComposeFile exec -T $DbService psql -U $PGUSR -d $PGDB -c "update easy_thumbnails_source set name = regexp_replace(name, '^products/', 'products/photos/') where name like 'products/%' and name not like 'products/photos/%';" | Out-Null
    } else {
      Write-Host ">> Canonical layout: products/ (flat) (files top-level: $cntFsFlat)"
      # переносим файлы из photos/ наверх (если есть)
      docker compose -f $ComposeFile exec -T $WebService sh -lc "
        if [ -d `"$MediaInContainer/products/photos`" ]; then
          for f in `"$MediaInContainer/products/photos`"/*; do
            [ -f `"$`"f`"$`" ] && mv `"$`"f`"$`" `"$MediaInContainer/products/`";
          done
          rmdir `"$MediaInContainer/products/photos`" 2>/dev/null || true
        fi
      "
      # правим БД — убираем photos/
      docker compose -f $ComposeFile exec -T $DbService psql -U $PGUSR -d $PGDB -c "update shop_product set image = regexp_replace(image, '^products/photos/', 'products/') where image like 'products/photos/%';" | Out-Null
      docker compose -f $ComposeFile exec -T $DbService psql -U $PGUSR -d $PGDB -c "update easy_thumbnails_source set name = regexp_replace(name, '^products/photos/', 'products/') where name like 'products/photos/%';" | Out-Null
    }

    # 5) быстрая проверка 3-х случайных путей
    Write-Host ">> Media sample check (3 paths from DB):"
    docker compose -f $ComposeFile exec -T $DbService psql -U $PGUSR -d $PGDB -tAc "select image from shop_product where image is not null limit 3;" | ForEach-Object {
      $p = $_.Trim()
      if ($p) {
        $exists = (docker compose -f $ComposeFile exec -T $WebService sh -lc "[ -f `"$MediaInContainer/$p`" ] && echo OK || echo MISSING").Trim()
        Write-Host ("   {0}: {1}" -f $exists, $p)
      }
    }
  } else {
    Write-Warning "Media zip not found, restored DB only."
  }

  Write-Host ">> Starting web"
  Dc-StartQuiet $WebService

  Write-Host "OK: restore finished"
  Write-Host " - DB: $DumpPath"
  if ($MediaZipPath) { Write-Host " - media: $MediaZipPath" }
  exit 0
}
