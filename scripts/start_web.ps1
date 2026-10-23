$ErrorActionPreference = "Continue"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
$StartupLog = Join-Path $LogDir "startup.log"
$ServerLog = Join-Path $LogDir "web-server.log"
$ServerErrLog = Join-Path $LogDir "web-server.err.log"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Main = Join-Path $ProjectRoot "main.py"
$Web = Join-Path $ProjectRoot "web.py"
$Port = 5000
$LocalDbInstance = "QuanLyPhongTro2025"
$SqlLocalDb = "C:\Program Files\Microsoft SQL Server\170\Tools\Binn\SqlLocalDB.exe"

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

function Write-StartupLog {
    param([string] $Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp $Message" | Out-File -LiteralPath $StartupLog -Append -Encoding UTF8
}

Write-StartupLog "Startup script started."

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalAddress -in @("127.0.0.1", "0.0.0.0", "::") } |
    Select-Object -First 1

if ($listener) {
    Write-StartupLog "Port $Port is already listening. Process id: $($listener.OwningProcess)."
    exit 0
}

if (-not (Test-Path -LiteralPath $Python)) {
    Write-StartupLog "Python virtual environment was not found: $Python"
    exit 1
}

if (Test-Path -LiteralPath $SqlLocalDb) {
    Write-StartupLog "Starting LocalDB instance $LocalDbInstance."
    & $SqlLocalDb start $LocalDbInstance *>> $StartupLog
} else {
    Write-StartupLog "SqlLocalDB.exe was not found at $SqlLocalDb."
}

Write-StartupLog "Running database initialization check."
& $Python $Main init-db *>> $StartupLog
Write-StartupLog "Database initialization exit code: $LASTEXITCODE"

Write-StartupLog "Starting Flask web server on http://127.0.0.1:$Port"
Start-Process `
    -FilePath $Python `
    -ArgumentList "`"$Web`"" `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $ServerLog `
    -RedirectStandardError $ServerErrLog

Start-Sleep -Seconds 3
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalAddress -in @("127.0.0.1", "0.0.0.0", "::") } |
    Select-Object -First 1

if ($listener) {
    Write-StartupLog "Web server is listening on port $Port. Process id: $($listener.OwningProcess)."
    exit 0
}

Write-StartupLog "Web server did not start. Check $ServerErrLog."
exit 1
