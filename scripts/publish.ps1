# Publishes both packages.
#
# npm:  set NPM_TOKEN / pass -NpmToken. The version is only staged; approving it on
#       npmjs.com is a separate step (see release-npm.ps1).
# PyPI: set TWINE_USERNAME=__token__ and TWINE_PASSWORD=pypi-... / pass -PypiToken
#
# Usage:
#   powershell -File scripts\publish.ps1                      (build + publish both)
#   powershell -File scripts\publish.ps1 -Only npm
#   powershell -File scripts\publish.ps1 -Only pypi
#   powershell -File scripts\publish.ps1 -PypiToken pypi-AgEI... -NpmToken npm_...
param(
    [ValidateSet("all", "npm", "pypi")]
    [string]$Only = "all",
    [string]$PypiToken = $env:PYPI_TOKEN,
    [string]$NpmToken = $env:NPM_TOKEN
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Step($text) { Write-Host "`n== $text ==" -ForegroundColor Cyan }

if ($Only -in @("all", "pypi")) {
    Step "构建 Python 包"
    Push-Location $root
    Remove-Item -Recurse -Force dist, build -ErrorAction SilentlyContinue
    python -m build
    python -m twine check dist/*
    Pop-Location

    Step "上传到 PyPI"
    Push-Location $root
    if ($PypiToken) {
        $env:TWINE_USERNAME = "__token__"
        $env:TWINE_PASSWORD = $PypiToken
    }
    if (-not $env:TWINE_PASSWORD) {
        Write-Host "缺少凭据。设置 `$env:TWINE_PASSWORD='pypi-...' 或传 -PypiToken。" -ForegroundColor Yellow
        exit 1
    }
    python -m twine upload --non-interactive dist/*
    Pop-Location
}

if ($Only -in @("all", "npm")) {
    Step "暂存 dsh-ai-os"
    & (Join-Path $PSScriptRoot "release-npm.ps1") -Token $NpmToken
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "`n完成。" -ForegroundColor Green
