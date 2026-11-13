# Levanta la Tienda de Cuentos IA despues de prender o reiniciar la compu.
# Uso: doble clic en iniciar.bat, o en PowerShell:
#   powershell -ExecutionPolicy Bypass -File .\iniciar.ps1

$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot   # siempre trabaja en la carpeta del proyecto

function Paso($texto) { Write-Host "`n==> $texto" -ForegroundColor Cyan }

# 1. Docker Desktop
Paso "Verificando Docker..."
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    $docker = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $docker)) {
        Write-Host "No encuentro Docker Desktop. Instalalo desde https://www.docker.com/products/docker-desktop/" -ForegroundColor Red
        Read-Host "Enter para salir"; exit 1
    }
    Write-Host "Abriendo Docker Desktop (puede tardar 1 o 2 minutos)..."
    Start-Process $docker
    $limite = (Get-Date).AddMinutes(4)
    do {
        Start-Sleep -Seconds 5
        Write-Host "." -NoNewline
        docker info *> $null
    } until ($LASTEXITCODE -eq 0 -or (Get-Date) -gt $limite)
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`nDocker no arranco. Abrilo a mano y fijate si muestra algun error (por ejemplo WSL)." -ForegroundColor Red
        Read-Host "Enter para salir"; exit 1
    }
}
Write-Host "Docker funcionando." -ForegroundColor Green

# 2. Archivos necesarios
foreach ($archivo in "compose.yaml", "Dockerfile") {
    if (-not (Test-Path $archivo)) {
        Write-Host "Falta $archivo en $PSScriptRoot. Este script tiene que estar en la carpeta del proyecto." -ForegroundColor Red
        Read-Host "Enter para salir"; exit 1
    }
}
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Cree el archivo .env a partir de .env.example. Revisalo si queres usar IA real o Telegram." -ForegroundColor Yellow
}

# Clave de cifrado de n8n: compose.yaml la exige. Si falta, se genera una al azar.
# IMPORTANTE: una vez creada no se cambia, o n8n no puede leer sus credenciales.
$rutaEnv = Join-Path $PSScriptRoot ".env"
$textoEnv = [IO.File]::ReadAllText($rutaEnv)
if ($textoEnv -notmatch '(?m)^N8N_ENCRYPTION_KEY=\S+') {
    $clave = -join (1..32 | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) })
    if ($textoEnv -match '(?m)^N8N_ENCRYPTION_KEY=[ \t]*\r?$') {
        $textoEnv = $textoEnv -replace '(?m)^N8N_ENCRYPTION_KEY=[ \t]*(\r?)$', "N8N_ENCRYPTION_KEY=$clave`$1"
    } else {
        $textoEnv = $textoEnv.TrimEnd() + "`r`nN8N_ENCRYPTION_KEY=$clave`r`n"
    }
    [IO.File]::WriteAllText($rutaEnv, $textoEnv, (New-Object Text.UTF8Encoding $false))
    Write-Host "Genere N8N_ENCRYPTION_KEY en .env (no la cambies despues)." -ForegroundColor Yellow
}

# 3. Levantar los servicios
Paso "Levantando API, panel y n8n..."
docker compose up -d --build
if ($LASTEXITCODE -ne 0) {
    Write-Host "Fallo docker compose. Copia el error de arriba y mandalo." -ForegroundColor Red
    Read-Host "Enter para salir"; exit 1
}

# 4. Esperar a que la API responda
Paso "Esperando a que la API este lista..."
$limite = (Get-Date).AddMinutes(2)
$lista = $false
do {
    try { Invoke-RestMethod "http://localhost:8000/salud" -TimeoutSec 3 | Out-Null; $lista = $true }
    catch { Start-Sleep -Seconds 3; Write-Host "." -NoNewline }
} until ($lista -or (Get-Date) -gt $limite)

if (-not $lista) {
    Write-Host "`nLa API no responde. Ultimas lineas del log:" -ForegroundColor Red
    docker compose logs api --tail 30
    Read-Host "Enter para salir"; exit 1
}

# 5. Cargar los cuentos de ejemplo (si ya estan, los saltea)
Paso "Cargando cuentos de ejemplo..."
docker compose exec -T api python -m scripts.cargar_ejemplos

# 6. Resumen y navegador
docker compose ps
Write-Host "`nTodo listo:" -ForegroundColor Green
Write-Host "  Panel  http://localhost:8501"
Write-Host "  API    http://localhost:8000/docs"
Write-Host "  n8n    http://localhost:5678"
Start-Process "http://localhost:8501"
Read-Host "`nEnter para cerrar esta ventana (los servicios siguen funcionando)"
