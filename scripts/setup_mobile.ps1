# Cài đặt để dùng app trên điện thoại (chạy lại nhiều lần vẫn an toàn):
#   1. Tạo môi trường Python + database (nếu chưa có)
#   2. Tạo tài khoản chủ nhà (nếu chưa có)
#   3. Mở web ra Internet bằng Tailscale Funnel (nếu đã cài Tailscale)
#   4. Ghi instance\web.env: TRUST_PROXY=1, PUBLIC_URL=<địa chỉ tunnel>
#
# Cách chạy (PowerShell, trong thư mục dự án):
#   powershell -ExecutionPolicy Bypass -File scripts\setup_mobile.ps1
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$EnvFile = Join-Path $ProjectRoot "instance\web.env"
$Port = 5000
Set-Location $ProjectRoot

function Step($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }

function Set-EnvValue([string] $Key, [string] $Value) {
    New-Item -ItemType Directory -Force -Path (Split-Path $EnvFile) | Out-Null
    $lines = @()
    if (Test-Path $EnvFile) { $lines = @(Get-Content $EnvFile -Encoding UTF8) }
    $found = $false
    $lines = @($lines | ForEach-Object {
        if ($_ -match "^\s*#?\s*$Key\s*=") { $found = $true; "$Key=$Value" } else { $_ }
    })
    if (-not $found) { $lines += "$Key=$Value" }
    Set-Content -Path $EnvFile -Value $lines -Encoding UTF8
}

Step "1/4 Python + database"
if (-not (Test-Path $Python)) {
    python -m venv .venv
    & $Python -m pip install -q -r requirements.txt
}
& $Python main.py init-db
if ($LASTEXITCODE -ne 0) { throw "Khong khoi tao duoc database. Kiem tra SQL Server / LocalDB." }

Step "2/4 Tai khoan chu nha"
& $Python -c "import sys; from src.auth import has_any_user; sys.exit(0 if has_any_user() else 1)"
if ($LASTEXITCODE -eq 0) {
    Write-Host "Da co tai khoan. (Doi mat khau: vao app > Tai khoan, hoac: python main.py create-owner)"
} else {
    & $Python main.py create-owner
    if ($LASTEXITCODE -ne 0) { throw "Chua tao duoc tai khoan." }
}

Step "3/4 Mo web ra Internet (HTTPS)"
$publicUrl = ""
$tailscale = Get-Command tailscale -ErrorAction SilentlyContinue
if ($tailscale) {
    & tailscale funnel --bg $Port
    if ($LASTEXITCODE -eq 0) {
        $status = (& tailscale status --json) -join "`n" | ConvertFrom-Json
        $dns = "$($status.Self.DNSName)".TrimEnd(".")
        if ($dns) { $publicUrl = "https://$dns" }
    } else {
        Write-Host "Tailscale Funnel chua bat duoc (can dang nhap Tailscale va cho phep Funnel trong trang quan tri)." -ForegroundColor Yellow
    }
} else {
    Write-Host "Chua cai Tailscale. Tai tai https://tailscale.com/download roi chay lai script nay," -ForegroundColor Yellow
    Write-Host "hoac nhap dia chi Cloudflare Tunnel cua ban ben duoi." -ForegroundColor Yellow
}
if (-not $publicUrl) {
    $publicUrl = (Read-Host "Dia chi HTTPS cong khai (vd https://nha.example.com, Enter de bo qua)").Trim().TrimEnd("/")
}

Step "4/4 Ghi cau hinh instance\web.env"
Set-EnvValue "TRUST_PROXY" "1"
if ($publicUrl) { Set-EnvValue "PUBLIC_URL" $publicUrl }
Write-Host "Da ghi $EnvFile"

Write-Host ""
Write-Host "XONG. Khoi dong lai web (scripts\start_web.ps1) roi tren dien thoai mo:" -ForegroundColor Green
if ($publicUrl) { Write-Host "   $publicUrl" -ForegroundColor Green } else { Write-Host "   <dia chi tunnel cua ban>" -ForegroundColor Green }
Write-Host "   iPhone: Safari > nut Chia se > Them vao MH chinh"
Write-Host "   Android: Chrome > menu > Cai dat ung dung"
Write-Host "Nho dat Windows khong ngu khi cam dien (Settings > System > Power)."
