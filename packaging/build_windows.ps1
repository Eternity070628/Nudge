param(
  [string]$Arch = $(if ($env:ARCH) { $env:ARCH } else { "x64" }),
  [string]$Python = $(if ($env:PYTHON) { $env:PYTHON } else { "python" }),
  [string]$Makensis = $env:MAKENSIS,
  [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Version = (Get-Content "packaging/version.txt" -Raw).Trim()
New-Item -ItemType Directory -Force -Path "dist", "build" | Out-Null

Write-Host "[build] PyInstaller $Version / windows-$Arch"
& $Python -m PyInstaller `
  --noconfirm --clean --onedir --windowed --name Nudge `
  --icon "packaging/assets/nudge.ico" `
  --add-data "backend/app/static;backend/app/static" `
  --paths backend `
  --collect-submodules uvicorn `
  --collect-submodules app `
  --hidden-import app.main `
  --distpath dist --workpath build `
  "packaging/nudge_entry.py"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败" }
if (-not (Test-Path "dist/Nudge/Nudge.exe")) { throw "缺少 dist/Nudge/Nudge.exe" }
if ($SkipInstaller) {
  Write-Host "[build] 已跳过 NSIS，仅生成 dist/Nudge/Nudge.exe"
  exit 0
}

if (-not $Makensis) {
  $cmd = Get-Command makensis.exe -ErrorAction SilentlyContinue
  if ($cmd) { $Makensis = $cmd.Source }
}
if (-not $Makensis) {
  $Makensis = @(
    "C:\Program Files (x86)\NSIS\makensis.exe",
    "C:\Program Files\NSIS\makensis.exe"
  ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Makensis) {
  $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
  if ($winget) {
    Write-Host "[build] 尝试 winget 安装 NSIS..."
    & $winget.Source install --id NSIS.NSIS -e --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
    $Makensis = @(
      "C:\Program Files (x86)\NSIS\makensis.exe",
      "C:\Program Files\NSIS\makensis.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
  }
}
if (-not $Makensis) {
  Write-Host "[build] 下载便携版 NSIS..."
  New-Item -ItemType Directory -Force -Path "build/nsis" | Out-Null
  $zip = Join-Path $Root "build/nsis.zip"
  try {
    Invoke-WebRequest -Uri "https://downloads.sourceforge.net/project/nsis/NSIS%203/3.11/nsis-3.11.zip" -OutFile $zip -UseBasicParsing -UserAgent "Mozilla/5.0"
  } catch {
    Invoke-WebRequest -Uri "https://sourceforge.net/projects/nsis/files/NSIS%203/3.11/nsis-3.11.zip/download" -OutFile $zip -UseBasicParsing -UserAgent "Mozilla/5.0"
  }
  Expand-Archive -Path $zip -DestinationPath "build/nsis" -Force
  $Makensis = Get-ChildItem "build/nsis" -Recurse -Filter makensis.exe | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $Makensis) { throw "未找到或无法安装 NSIS makensis.exe" }

Write-Host "[build] NSIS $Makensis"
& $Makensis "/DVERSION=$Version" "/DARCH=$Arch" "/DDISTDIR=$Root\dist" "/DASSETDIR=$Root\packaging\assets" "packaging/windows/nudge.nsi"
if ($LASTEXITCODE -ne 0) { throw "NSIS 安装器构建失败" }
$Installer = Join-Path $Root "dist/Nudge-$Version-windows-$Arch-setup.exe"
if (-not (Test-Path $Installer)) { throw "缺少安装器 $Installer" }

function Sign-NudgeFile([string]$Path) {
  if (-not $env:WINDOWS_PFX_BASE64) {
    Write-Host "[build] 未配置 Windows 代码签名证书，跳过签名：$Path"
    return
  }
  $signtool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
  if (-not $signtool) {
    $signtool = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
      Where-Object { $_.FullName -match "x64" } | Select-Object -First 1 -ExpandProperty FullName
  }
  if (-not $signtool) {
    Write-Warning "已配置证书但找不到 signtool.exe，跳过签名"
    return
  }
  $pfx = Join-Path $Root "build/nudge-sign.pfx"
  [IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:WINDOWS_PFX_BASE64))
  try {
    & $signtool sign /f $pfx /p $env:WINDOWS_PFX_PASSWORD /fd sha256 /tr "http://timestamp.digicert.com" /td sha256 $Path
    if ($LASTEXITCODE -ne 0) { throw "签名失败：$Path" }
  } finally {
    Remove-Item $pfx -Force -ErrorAction SilentlyContinue
  }
}

Sign-NudgeFile (Join-Path $Root "dist/Nudge/Nudge.exe")
Sign-NudgeFile $Installer
Write-Host "[build] 完成：$Installer"