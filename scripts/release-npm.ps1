# Releases dsh-ai-os to npm, together with the market index that describes the release.
#
#   1. bump version in integrations/dsh-ai-os/package.json
#   2. powershell -File scripts\release-npm.ps1 -Token npm_xxx
#   3. approve the staged version at https://www.npmjs.com/settings/<user>/packages (2FA)
#   4. powershell -File scripts\release-npm.ps1 -PurgeCdn
#
# This account's tokens can only stage (E_STAGE_REQUIRED), and `npm stage` needs npm >= 12,
# so a private npm 12 is installed under %TEMP%\npm12 on first use.
# The step-by-step version is in scripts/RELEASE.md.
param(
    [string]$Token = $env:NPM_TOKEN,
    [switch]$SkipIndexRefresh,
    [switch]$PurgeCdn
)

# Native commands write warnings to stderr; "Stop" would turn those into exceptions.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$pkg = Join-Path $root "integrations\dsh-ai-os"
$registry = "https://registry.npmjs.org/"
$stableIndex = "https://cdn.jsdelivr.net/npm/dsh-ai-os/market-index.json"

function Step($text) { Write-Host "`n== $text ==" -ForegroundColor Cyan }

$version = (Get-Content (Join-Path $pkg "package.json") -Raw | ConvertFrom-Json).version

if ($PurgeCdn) {
    Step "刷新 jsDelivr 缓存"
    $published = (npm view "dsh-ai-os@$version" version --registry $registry 2>$null)
    if ($published -ne $version) {
        Write-Host "$version 还没上线（未批准或仍在校验）。批准后再运行。" -ForegroundColor Yellow
        exit 1
    }
    curl.exe -s "https://purge.jsdelivr.net/npm/dsh-ai-os/market-index.json" | Out-Null
    Start-Sleep 5
    $served = (curl.exe -s $stableIndex | ConvertFrom-Json).plugins[0].versions[0].version
    if ($served -ne $version) {
        Write-Host "固定索引地址仍返回 $served，稍等几分钟再运行一次。" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "固定索引地址已指向 $version：$stableIndex" -ForegroundColor Green
    exit 0
}

if (-not $Token) {
    Write-Host "缺少 token。用 -Token npm_... 传入，或先设置 `$env:NPM_TOKEN。" -ForegroundColor Yellow
    Write-Host "创建地址：https://www.npmjs.com/settings/~/tokens" -ForegroundColor Yellow
    exit 1
}

$npmrc = Join-Path $env:TEMP "aios-npmrc"
"registry=$registry`n//registry.npmjs.org/:_authToken=$Token" |
    Set-Content -Path $npmrc -Encoding ASCII -NoNewline
$env:npm_config_userconfig = $npmrc

try {
    Step "校验 token"
    $who = npm whoami --registry $registry 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Host "token 无效或已过期" -ForegroundColor Red; exit 1 }
    Write-Host "已认证为 $who"

    $existing = npm view "dsh-ai-os@$version" version --registry $registry 2>$null
    if ($existing -eq $version) {
        Write-Host "$version 已经发布过。先改 package.json 的 version。" -ForegroundColor Red
        exit 1
    }

    if (-not $SkipIndexRefresh) {
        Step "生成索引（指向 $version）"
        python (Join-Path $root "scripts\build_market_index.py")
        if ($LASTEXITCODE -ne 0) { exit 1 }
    }

    Step "校验索引"
    node (Join-Path $root "scripts\validate_market_index.mjs") (Join-Path $pkg "market-index.json") $stableIndex
    if ($LASTEXITCODE -ne 0) { exit 1 }

    $npm12 = Join-Path $env:TEMP "npm12\node_modules\npm\bin\npm-cli.js"
    if (-not (Test-Path $npm12)) {
        Step "安装 npm 12（npm stage 需要）"
        npm install --registry $registry --prefix (Join-Path $env:TEMP "npm12") npm@12 2>$null
        if (-not (Test-Path $npm12)) { Write-Host "npm 12 安装失败" -ForegroundColor Red; exit 1 }
    }

    Step "暂存 $version"
    Push-Location $pkg
    node $npm12 stage publish . --registry $registry --access public 2>&1 |
        Where-Object { "$_" -notmatch "does not support Node.js" }
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Write-Host "暂存失败" -ForegroundColor Red; exit $code }
} finally {
    Remove-Item $npmrc -ErrorAction SilentlyContinue
    Remove-Item Env:npm_config_userconfig -ErrorAction SilentlyContinue
}

Write-Host "`n已暂存 $version，还差两步：" -ForegroundColor Green
Write-Host "  1. 约 1 分钟校验完成后，到这里用 2FA 点「批准」："
Write-Host "     https://www.npmjs.com/settings/$who/packages"
Write-Host "  2. 批准后刷新 CDN，让固定索引地址指向新版本："
Write-Host "     powershell -File scripts\release-npm.ps1 -PurgeCdn"
Write-Host ""
Write-Host "  固定索引地址: $stableIndex"
Write-Host "  备用地址    : https://unpkg.com/dsh-ai-os@$version/market-index.json"
