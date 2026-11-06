<#
.SYNOPSIS
  Prepares and starts the whole ISRO assistant from scratch, then waits until every part is healthy.

.DESCRIPTION
  1. checks Docker
  2. creates .env from .env.example (generates local passwords + JWT secret) and checks the Azure settings
  3. builds the images
  4. starts Postgres, Redis, Qdrant
  5. Wikipedia articles: downloads / updates them only when WIKI_DOWNLOAD=true (or -DownloadWiki), then
     verifies every article is present before moving on; otherwise uses the articles in "wiki documents/"
  6. builds the knowledge base in Qdrant (verify docs -> chunk -> embed -> index -> verify); skipped when unchanged
  7. starts the MCP servers, API (runs DB migrations), frontend and pgAdmin
  8. waits until /api/health reports every dependency OK, then prints the URLs

  Re-running is safe: finished steps are detected and skipped.

.EXAMPLE
  .\setup.ps1                  # use the committed articles (WIKI_DOWNLOAD from .env, default false)
  .\setup.ps1 -DownloadWiki    # fetch new Wikipedia articles first
  .\setup.ps1 -Reindex         # rebuild the Qdrant index even if nothing changed
#>
param(
  [switch]$DownloadWiki,
  [switch]$Reindex
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Step($n, $msg) { Write-Host ""; Write-Host "[$n/8] $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "  OK  $msg" -ForegroundColor Green }
function Die($msg) { Write-Host ""; Write-Host "  FAILED: $msg" -ForegroundColor Red; exit 1 }
function Compose { & docker compose @args; if ($LASTEXITCODE -ne 0) { Die "docker compose $($args -join ' ') (exit $LASTEXITCODE)" } }
function NewSecret { -join ((1..32) | ForEach-Object { "{0:x2}" -f (Get-Random -Minimum 0 -Maximum 256) }) }

function Read-DotEnv($path) {
  $map = [ordered]@{}
  foreach ($line in [IO.File]::ReadAllLines($path)) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { $map[$Matches[1]] = $Matches[2].Trim() }
  }
  return $map
}

function Set-DotEnvValue($path, $key, $value) {
  $lines = [Collections.Generic.List[string]][IO.File]::ReadAllLines($path)
  $i = $lines.FindIndex({ param($l) $l -match "^$key=" })
  if ($i -ge 0) { $lines[$i] = "$key=$value" } else { $lines.Add("$key=$value") }
  [IO.File]::WriteAllLines($path, $lines, (New-Object Text.UTF8Encoding($false)))   # no BOM
}

# ------------------------------------------------------------------------------------------------
Step 1 "Checking Docker"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Die "Docker is not installed. Install Docker Desktop: https://docs.docker.com/desktop/" }
& docker info *> $null
if ($LASTEXITCODE -ne 0) { Die "Docker is installed but not running. Start Docker Desktop and run this script again." }
& docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Die "Docker Compose v2 is required (docker compose ...)." }
Ok (& docker --version)

# ------------------------------------------------------------------------------------------------
Step 2 "Configuration (.env)"
$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) {
  Copy-Item ".env.example" $envFile
  Ok "created .env from .env.example"
}
$cfg = Read-DotEnv $envFile
foreach ($k in "POSTGRES_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET") {
  if (-not $cfg[$k]) { Set-DotEnvValue $envFile $k (NewSecret); Ok "generated $k" }
}
$cfg = Read-DotEnv $envFile
$missing = @("LLM_BASE_URL", "LLM_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY") |
  Where-Object { -not $cfg[$_] -or $cfg[$_] -match '<resource>' }
if ($missing) { Die "fill in these Azure settings in .env, then run again: $($missing -join ', ')" }
if (-not $cfg["SPEECH_KEY"]) { Write-Host "  note: SPEECH_KEY is empty - voice questions are disabled, text chat works" -ForegroundColor Yellow }
$wiki = $DownloadWiki.IsPresent -or ($cfg["WIKI_DOWNLOAD"] -match '^(?i)(true|1|yes)$')
Ok "Azure settings present; WIKI_DOWNLOAD=$wiki"

# ------------------------------------------------------------------------------------------------
Step 3 "Building images (first run takes a few minutes)"
Compose --profile jobs build
Ok "images built"

# ------------------------------------------------------------------------------------------------
Step 4 "Starting Postgres, Redis and Qdrant"
Compose up -d --wait postgres redis qdrant
Ok "infrastructure healthy"

# ------------------------------------------------------------------------------------------------
Step 5 "Wikipedia articles"
if ($wiki) {
  Write-Host "  downloading new articles (already downloaded ones are skipped)..."
  Compose --profile jobs run --rm wiki
  Write-Host "  checking that every article was downloaded..."
  Compose --profile jobs run --rm ingest "/app/isro rag/.venv/bin/python" build_knowledge_base.py --verify-docs
  Ok "articles downloaded and verified"
} else {
  Write-Host "  WIKI_DOWNLOAD=false - skipping the download, using the articles in 'wiki documents/'"
  Compose --profile jobs run --rm ingest "/app/isro rag/.venv/bin/python" build_knowledge_base.py --verify-docs
  Ok "articles verified"
}

# ------------------------------------------------------------------------------------------------
Step 6 "Building the knowledge base in Qdrant"
if ($Reindex) { Compose --profile jobs run --rm ingest "/app/isro rag/.venv/bin/python" build_knowledge_base.py --force }
else { Compose --profile jobs run --rm ingest }
Ok "knowledge base ready"

# ------------------------------------------------------------------------------------------------
Step 7 "Starting MCP servers, API, frontend and pgAdmin"
Compose up -d --wait mcp api frontend pgadmin
Ok "application containers healthy"

# ------------------------------------------------------------------------------------------------
Step 8 "Waiting until every dependency reports OK"
$front = if ($cfg["FRONTEND_PORT"]) { $cfg["FRONTEND_PORT"] } else { "3000" }
$healthUrl = "http://localhost:$front/api/health"
$deadline = (Get-Date).AddMinutes(5)
$health = $null
while ((Get-Date) -lt $deadline) {
  try { $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 10 } catch {
    try { $health = $_.ErrorDetails.Message | ConvertFrom-Json } catch { $health = $null }
  }
  if ($health -and $health.status -eq "ok") { break }
  Start-Sleep -Seconds 5
}
if (-not $health -or $health.status -ne "ok") {
  if ($health) { $health.checks | ConvertTo-Json -Depth 4 | Write-Host }
  Die "not every dependency is healthy - see above and 'docker compose logs api mcp'"
}
foreach ($p in $health.checks.PSObject.Properties) { Ok $p.Name }

$pg = if ($cfg["PGADMIN_PORT"]) { $cfg["PGADMIN_PORT"] } else { "5050" }
$qd = if ($cfg["QDRANT_PORT"]) { $cfg["QDRANT_PORT"] } else { "6333" }
$api = if ($cfg["API_PORT"]) { $cfg["API_PORT"] } else { "8000" }
Write-Host ""
Write-Host "ISRO assistant is ready." -ForegroundColor Green
Write-Host "  App        http://localhost:$front          (create an account and ask a question)"
Write-Host "  API docs   http://localhost:$api/docs"
Write-Host "  Qdrant     http://localhost:$qd/dashboard"
Write-Host "  pgAdmin    http://localhost:$pg"
Write-Host ""
Write-Host "Admin account (emails in ADMIN_EMAILS cannot sign up publicly) - choose its password with:"
Write-Host "  docker compose exec api .venv/bin/python scripts/create_admin.py"
Write-Host "Stop: docker compose stop    |    Remove everything incl. data: docker compose down -v"
