param(
  [Parameter(Mandatory=$true)][string]$Version,
  [string]$NotesFile = "",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$nl = [Environment]::NewLine

function Fail($msg) { Write-Host "FAIL: $msg" -ForegroundColor Red; exit 1 }
function Sep($msg) { Write-Host $msg -ForegroundColor Cyan }

if (-not (Test-Path ".git")) { Fail "当前目录不是 git 仓库（缺少 .git）" }
$remote = (git remote get-url origin 2>$null)
if (-not $remote) { Fail "未配置 remote origin" }
if ($remote -notmatch 'github[.]com[:/](?<slug>[^/]+/[^/.]+)') { Fail "remote 不是 GitHub: $remote" }
$slug = $Matches['slug'] -replace '[.]git$',''
Write-Host "repo   : $slug"
Write-Host "remote : $remote"

# 凭据：从本机凭据管理器取，不打印、不落盘
$in = "protocol=https" + [char]10 + "host=github.com" + [char]10 + [char]10
$cred = ($in | git credential fill 2>$null) -join [char]10
if ($cred -notmatch 'password=([^\s]+)') { Fail "本机取不到 GitHub 凭据（git credential fill 无返回），先 git push 一次并登录" }
$tok = $Matches[1]
$h = @{ Authorization = "token $tok"; "User-Agent" = "nudge-release"; Accept = "application/vnd.github+json" }

$user = Invoke-RestMethod -Uri "https://api.github.com/user" -Headers $h -TimeoutSec 30
Write-Host "auth   : $($user.login)"

git add -A
$dirty = (git status --porcelain)
if ($dirty) {
  git commit -q -m "chore: release $Version"
  Write-Host "commit : 已提交本次改动"
} else {
  Write-Host "commit : 无改动，跳过提交"
}
$sha = (git rev-parse --short HEAD).Trim()

if ($DryRun) {
  Sep "dry-run: 校验通过（repo / 凭据 / 登录），未推送、未建 tag、未发布"
  exit 0
}

git push -q origin HEAD
Write-Host "pushed : $sha"

if (-not (git tag --list $Version)) { git tag $Version }
git push -q origin $Version
Write-Host "tag    : $Version"

# 打包：仅含已跟踪文件
$zip = Join-Path $env:TEMP "Nudge-$Version-source.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
git archive --format=zip --prefix="Nudge-$Version/" -o $zip HEAD

# 发布说明
if ($NotesFile -and (Test-Path $NotesFile)) {
  $notes = Get-Content $NotesFile -Raw -Encoding UTF8
} else {
  $prev = (git describe --tags --abbrev=0 "$Version^" 2>$null)
  $range = if ($prev) { "$prev..HEAD" } else { "HEAD" }
  $log = (git log --pretty=format:"- %s (%h)" $range)
  $notes = "## Nudge $Version" + $nl + $nl + "### 本次变更" + $nl + $log + $nl + $nl + "### 验证" + $nl + "- 提交 $sha 已推送，tag $Version 指向该提交" + $nl + "- 源码包由 git archive 生成，仅含已跟踪文件（无数据库、无 __pycache__）"
}

$body = @{ tag_name = $Version; target_commitish = "main"; name = "Nudge $Version"; body = $notes; draft = $false; prerelease = $false } | ConvertTo-Json -Depth 4
$bytes = [Text.Encoding]::UTF8.GetBytes($body)

try {
  $rel = Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$slug/releases" -Headers $h -Body $bytes -ContentType "application/json; charset=utf-8" -TimeoutSec 60
} catch {
  $resp = $_.Exception.Response
  if ($resp -and $resp.StatusCode.value__ -eq 422) {
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$slug/releases/tags/$Version" -Headers $h -TimeoutSec 30
    Write-Host "release: 已存在，复用现有 release" -ForegroundColor Yellow
  } else { throw }
}
Write-Host "release: $($rel.html_url)"

$assetName = "Nudge-$Version-source.zip"
$assets = Invoke-RestMethod -Uri "https://api.github.com/repos/$slug/releases/$($rel.id)/assets" -Headers $h -TimeoutSec 30
$old = $assets | Where-Object { $_.name -eq $assetName }
if ($old) {
  Invoke-RestMethod -Method Delete -Uri "https://api.github.com/repos/$slug/releases/assets/$($old.id)" -Headers $h -TimeoutSec 30
}
$up = Invoke-RestMethod -Method Post -Uri "https://uploads.github.com/repos/$slug/releases/$($rel.id)/assets?name=$assetName" -Headers $h -InFile $zip -ContentType "application/zip" -TimeoutSec 120
Write-Host "asset  : $($up.browser_download_url) ($([math]::Round($up.size/1kb)) KB)"
Sep "DONE: $Version 已发布，源码包已上传"
