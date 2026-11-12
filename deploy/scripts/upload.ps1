# 把本地构建产物同步到服务器（在 Windows 上跑）
#
# 前提：本机已装 OpenSSH 客户端（Win10+ 自带 scp / ssh），且能用密钥登录服务器。
# 用法：
#   powershell -ExecutionPolicy Bypass -File deploy\scripts\upload.ps1 `
#       -Server "root@1.2.3.4" -RemoteDir "/srv/travel"
param(
  [Parameter(Mandatory = $true)][string]$Server,
  [string]$RemoteDir = "/srv/travel",
  [string]$SshKey = "$env:USERPROFILE\.ssh\id_ed25519"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$KeyArg = @()
if (Test-Path $SshKey) { $KeyArg = @("-i", $SshKey) }

function Push($Local, $Remote) {
  Write-Host "==> $Local -> $Remote"
  & scp @KeyArg -r $Local "${Server}:${Remote}"
  if ($LASTEXITCODE -ne 0) { throw "scp 失败：$Local" }
}

# 1) 后端代码（排除虚拟环境、缓存、日志、本地上传的测试图）
$api = Join-Path $Root "travel-api"
$tmp = Join-Path $env:TEMP "travel-api-upload"
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp | Out-Null
robocopy $api $tmp /E /XD ".venv" "__pycache__" ".pytest_cache" "logs" /XF "*.pyc" ".env" | Out-Null
Push $tmp "${RemoteDir}/travel-api"

# 2) 静态图片（POI 实景图 / 封面，别漏，否则小程序裂图）
Push (Join-Path $api "static") "${RemoteDir}/travel-api/static"

# 3) 前端构建产物（先在本地 npm run build）
$portalDist = Join-Path $Root "travel-portal\dist"
if (Test-Path $portalDist) { Push $portalDist "${RemoteDir}/www" } else { Write-Warning "缺 travel-portal\dist，先 npm run build" }

$webDist = Join-Path $Root "travel-web\dist"
if (Test-Path $webDist) { Push $webDist "${RemoteDir}/admin" } else { Write-Warning "缺 travel-web\dist，先 npm run build" }

# 4) 部署脚本与配置模板
Push (Join-Path $Root "deploy") "${RemoteDir}/deploy"

Write-Host "上传完成。到服务器执行：bash ${RemoteDir}/deploy/scripts/deploy.sh"
