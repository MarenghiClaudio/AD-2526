<#
.SYNOPSIS
    Benchmark automatizzato: DB setup + Locust con e senza cache Redis.

.PARAMETER Users
    Numero di utenti Locust simultanei (default: 50)
.PARAMETER SpawnRate
    Velocità di spawn utenti/s (default: 5)
.PARAMETER Duration
    Durata di ogni run (es. "60s", "2m", default: "60s")

.EXAMPLE
    .\benchmark.ps1
    .\benchmark.ps1 -Users 100 -SpawnRate 10 -Duration 2m
#>
param(
    [int]   $Users          = 50,
    [int]   $SpawnRate      = 5,
    [string]$Duration       = "60s",
    [string]$WarmupDuration = "45s",
    [int]   $CooldownSec    = 10
)

$ErrorActionPreference = "Stop"

$ROOT              = $PSScriptRoot
$BACKEND_DIR       = Join-Path $ROOT "backend"
$SOCIAL_NETWORK_DIR = Join-Path $ROOT "social_network"
$ENV_FILE          = Join-Path $BACKEND_DIR ".env"
$RESULTS_DIR       = Join-Path $ROOT "benchmark_results"
$HOST_URL          = "http://127.0.0.1:8000"

New-Item -ItemType Directory -Force -Path $RESULTS_DIR | Out-Null

# ─── Helpers ────────────────────────────────────────────────────────────────

function Write-Step($msg) {
    Write-Host "`n>>> $msg" -ForegroundColor Cyan
}

function Write-OK($msg) {
    Write-Host "    [OK] $msg" -ForegroundColor Green
}

function Write-Err($msg) {
    Write-Host "    [ERR] $msg" -ForegroundColor Red
}

function Set-CacheEnabled([bool]$enabled) {
    $val = if ($enabled) { "true" } else { "false" }
    $content = Get-Content $ENV_FILE -Raw
    $content = $content -replace 'CACHE_ENABLED=\S*', "CACHE_ENABLED=$val"
    Set-Content -Path $ENV_FILE -Value $content.TrimEnd() -Encoding utf8
    Write-OK "CACHE_ENABLED=$val"
}

function Test-RedisAvailable {
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect("localhost", 6379)
        $tcp.Close()
        return $true
    } catch {
        return $false
    }
}

function Close-DbConnections {
    # Termina tutte le connessioni attive al DB tramite psycopg2,
    # cosi' DROP TABLE non resta in attesa di lock dal pool del backend.
    python -c @"
import psycopg2, sys
try:
    conn = psycopg2.connect(host='localhost', port=5432, user='postgres', password='admin', dbname='ad')
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(\"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='ad' AND pid <> pg_backend_pid()\")
    conn.close()
except Exception as e:
    print(f'[WARN] Close-DbConnections: {e}', file=sys.stderr)
"@
    Write-OK "Connessioni DB terminate"
}

function Build-Database {
    Write-Step "Creazione database"
    Close-DbConnections
    Push-Location $SOCIAL_NETWORK_DIR
    try {
        python main.py
        if ($LASTEXITCODE -ne 0) { throw "social_network/main.py ha fallito (exit $LASTEXITCODE)" }
        Write-OK "Database pronto"
    } finally {
        Pop-Location
    }
}

function Start-Backend {
    $logOut = Join-Path $RESULTS_DIR "backend.log"
    $logErr = Join-Path $RESULTS_DIR "backend_err.log"
    $proc = Start-Process python `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0") `
        -WorkingDirectory $BACKEND_DIR `
        -PassThru -NoNewWindow `
        -RedirectStandardOutput $logOut `
        -RedirectStandardError  $logErr
    return $proc
}

function Wait-Backend {
    param([int]$TimeoutSec = 60)
    Write-Host "    Attendo backend su $HOST_URL/health" -NoNewline
    $elapsed = 0
    while ($elapsed -lt $TimeoutSec) {
        try {
            $r = Invoke-WebRequest -Uri "$HOST_URL/health" -TimeoutSec 2 -ErrorAction Stop
            if ($r.StatusCode -eq 200) {
                Write-Host " pronto." -ForegroundColor Green
                return
            }
        } catch {}
        Write-Host "." -NoNewline
        Start-Sleep 2
        $elapsed += 2
    }
    Write-Host ""
    throw "Backend non risponde dopo ${TimeoutSec}s - controlla benchmark_results/backend_err.log"
}

function Stop-Backend($proc) {
    if ($proc -and !$proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep 5
        Write-OK "Backend fermato"
    }
}

function Run-Locust([string]$CsvPrefix) {
    $csvPath = Join-Path $RESULTS_DIR $CsvPrefix
    Write-Step "Locust  utenti=$Users  spawn=$SpawnRate/s  durata=$Duration"
    Write-Host "    CSV: $csvPath*.csv"
    Push-Location $BACKEND_DIR
    try {
        python -m locust -f locustfile.py `
            --host        $HOST_URL `
            --headless `
            --users       $Users `
            --spawn-rate  $SpawnRate `
            --run-time    $Duration `
            --csv         $csvPath
        if ($LASTEXITCODE -ne 0) {
            Write-Host "    [WARN] Locust exit $LASTEXITCODE (failures attese, vedi CSV)" -ForegroundColor Yellow
        } else {
            Write-OK "Risultati salvati"
        }
    } finally {
        Pop-Location
    }
}

function Save-DbSnapshot {
    Write-Step "Salvataggio snapshot DB"
    $envContent = Get-Content $ENV_FILE -Raw
    $pgUser     = if ($envContent -match 'POSTGRES_USER=(\S+)')     { $Matches[1] } else { 'postgres' }
    $pgPassword = if ($envContent -match 'POSTGRES_PASSWORD=(\S+)') { $Matches[1] } else { 'admin' }
    $pgDb       = if ($envContent -match 'POSTGRES_DB=(\S+)')       { $Matches[1] } else { 'ad' }
    $snapshotPath = Join-Path $RESULTS_DIR "db_snapshot.sql"
    $env:PGPASSWORD = $pgPassword
    try {
        pg_dump -U $pgUser -h localhost -f $snapshotPath $pgDb
        if ($LASTEXITCODE -ne 0) { throw "pg_dump ha fallito (exit $LASTEXITCODE)" }
        Write-OK "Snapshot salvato in $snapshotPath"
    } finally {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }
}

function Restore-DbSnapshot {
    Write-Step "Ripristino snapshot DB"
    $envContent = Get-Content $ENV_FILE -Raw
    $pgUser     = if ($envContent -match 'POSTGRES_USER=(\S+)')     { $Matches[1] } else { 'postgres' }
    $pgPassword = if ($envContent -match 'POSTGRES_PASSWORD=(\S+)') { $Matches[1] } else { 'admin' }
    $pgDb       = if ($envContent -match 'POSTGRES_DB=(\S+)')       { $Matches[1] } else { 'ad' }
    $snapshotPath = Join-Path $RESULTS_DIR "db_snapshot.sql"
    Close-DbConnections
    python -c @"
import psycopg2, sys
try:
    conn = psycopg2.connect(host='localhost', port=5432, user='$pgUser', password='$pgPassword', dbname='postgres')
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(\"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$pgDb' AND pid <> pg_backend_pid()\")
        cur.execute('DROP DATABASE IF EXISTS $pgDb')
        cur.execute('CREATE DATABASE $pgDb')
    conn.close()
except Exception as e:
    print(f'[ERR] Restore-DbSnapshot: {e}', file=sys.stderr)
    sys.exit(1)
"@
    if ($LASTEXITCODE -ne 0) { throw "Ricreazione DB fallita" }
    $env:PGPASSWORD = $pgPassword
    try {
        psql -U $pgUser -h localhost -d $pgDb -f $snapshotPath
        if ($LASTEXITCODE -ne 0) { throw "psql restore ha fallito (exit $LASTEXITCODE)" }
        Write-OK "DB ripristinato da snapshot"
    } finally {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }
}

function Invoke-Warmup {
    param([string]$Duration = "45s")
    Write-Step "Warm-up ($Duration) - risultati non salvati"
    Push-Location $BACKEND_DIR
    try {
        python -m locust -f locustfile.py `
            --host       $HOST_URL `
            --headless `
            --users      10 `
            --spawn-rate 10 `
            --run-time   $Duration
        if ($LASTEXITCODE -ne 0) {
            Write-Err "Warm-up exit $LASTEXITCODE (non bloccante)"
        } else {
            Write-OK "Warm-up completato"
        }
    } finally {
        Pop-Location
    }
}

# ─── Main ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "+----------------------------------------------+" -ForegroundColor Yellow
Write-Host "|   BENCHMARK  cache OFF  ->  cache ON         |" -ForegroundColor Yellow
Write-Host "+----------------------------------------------+" -ForegroundColor Yellow

Build-Database
Save-DbSnapshot

# ── Run 1: senza cache ───────────────────────────────────────────────────────
Write-Host "`n---  RUN 1: CACHE OFF  -----------------------" -ForegroundColor Magenta

Restore-DbSnapshot
Write-Step "Configurazione .env"
Set-CacheEnabled $false
Write-Step "Avvio backend"
$proc = Start-Backend
try {
    Wait-Backend
    Invoke-Warmup -Duration $WarmupDuration
    Run-Locust "no_cache"
} finally {
    Write-Step "Stop backend"
    Stop-Backend $proc
    Close-DbConnections
    Move-Item (Join-Path $RESULTS_DIR "backend.log")     (Join-Path $RESULTS_DIR "backend_no_cache.log")     -Force -ErrorAction SilentlyContinue
    Move-Item (Join-Path $RESULTS_DIR "backend_err.log") (Join-Path $RESULTS_DIR "backend_no_cache_err.log") -Force -ErrorAction SilentlyContinue
    Write-OK "Log backend salvati: backend_no_cache.log"
}

Write-Step "Cooldown tra i run"
Start-Sleep $CooldownSec
Write-OK "${CooldownSec}s trascorsi"

# ── Run 2: con cache ─────────────────────────────────────────────────────────
Write-Host "`n---  RUN 2: CACHE ON   -----------------------" -ForegroundColor Magenta

Write-Step "Controllo Redis"
if (-not (Test-RedisAvailable)) {
    Write-Err "Redis non raggiungibile su localhost:6379"
    Write-Host "    Avvia Redis e riprova: docker run -d -p 6379:6379 redis" -ForegroundColor Yellow
    exit 1
}
Write-OK "Redis raggiungibile su localhost:6379"

Restore-DbSnapshot
Write-Step "Configurazione .env"
Set-CacheEnabled $true
Write-Step "Avvio backend"
$proc = Start-Backend
try {
    Wait-Backend
    Invoke-Warmup -Duration $WarmupDuration
    Run-Locust "with_cache"
} finally {
    Write-Step "Stop backend"
    Stop-Backend $proc
    Close-DbConnections
    Move-Item (Join-Path $RESULTS_DIR "backend.log")     (Join-Path $RESULTS_DIR "backend_with_cache.log")     -Force -ErrorAction SilentlyContinue
    Move-Item (Join-Path $RESULTS_DIR "backend_err.log") (Join-Path $RESULTS_DIR "backend_with_cache_err.log") -Force -ErrorAction SilentlyContinue
    Write-OK "Log backend salvati: backend_with_cache.log"
    Set-CacheEnabled $false
}

# ── Riepilogo ────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "+----------------------------------------------+" -ForegroundColor Green
Write-Host "|  Benchmark completato!                       |" -ForegroundColor Green
Write-Host "+----------------------------------------------+" -ForegroundColor Green
Write-Host ""
Write-Host "  Risultati in: $RESULTS_DIR"
Write-Host "  no_cache_stats.csv    -> baseline PostgreSQL puro"
Write-Host "  with_cache_stats.csv  -> con Redis"
Write-Host ""
Write-Host "  Parametri: utenti=$Users  spawn=$SpawnRate/s  durata=$Duration" -ForegroundColor Cyan
Write-Host "  Warm-up:   $WarmupDuration per run  |  Cooldown: ${CooldownSec}s tra i run" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Confronta le colonne 50%% / 95%% / 99%% per endpoint." -ForegroundColor Yellow