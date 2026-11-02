<#
.SYNOPSIS
    Build the AutoCorrect Desktop Windows BETA distributables and publish them to the site.

.DESCRIPTION
    1. Generates the application icon.
    2. Runs PyInstaller (one-folder) via packaging/autocorrect.spec  -> dist/AutoCorrectDesktop/
    3. Smoke-tests the frozen executable (--version, --headless-check).
    4. Zips the folder as a portable build                              -> dist/installer/*.zip
    5. Compiles the Inno Setup installer (if ISCC.exe is available)    -> dist/installer/*-setup.exe
    6. Writes SHA-256 sums + release-manifest.json and copies everything to site/public/downloads/

.PARAMETER Channel
    Pre-release channel suffix, e.g. "beta.1". Default: beta.1

.EXAMPLE
    pwsh packaging/build_windows_beta.ps1 -Channel beta.1
#>
[CmdletBinding()]
param(
    [string]$Channel = "beta.1",
    [switch]$SkipInstaller,
    [switch]$SkipPublish
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$Version = (python -c "import sys; sys.path.insert(0,'src'); from autocorrect.version import APP_VERSION; print(APP_VERSION)").Trim()
$FullVersion = "$Version-$Channel"
$DistDir = Join-Path $Root "dist"
$AppDir = Join-Path $DistDir "AutoCorrectDesktop"
$OutDir = Join-Path $DistDir "installer"
$PublishDir = Join-Path $Root "site\public\downloads"

Write-Host "==> AutoCorrect Desktop $FullVersion (win64)" -ForegroundColor Cyan

# 0. Tooling
python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) { python -m pip install --quiet pyinstaller }

# 1. Icon
python (Join-Path $PSScriptRoot "make_icon.py")

# 2. PyInstaller one-folder
if (Test-Path $AppDir) { Remove-Item $AppDir -Recurse -Force }
python -m PyInstaller --noconfirm --clean --distpath $DistDir --workpath (Join-Path $DistDir "build") (Join-Path $PSScriptRoot "autocorrect.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# 3. Smoke test the frozen binary
$Exe = Join-Path $AppDir "AutoCorrectDesktop.exe"
$SmokeData = Join-Path $env:TEMP "autocorrect_beta_smoke"
if (Test-Path $SmokeData) { Remove-Item $SmokeData -Recurse -Force }
$ver = & $Exe --version 2>&1 | Out-String
Write-Host "    $($ver.Trim())"
$check = & $Exe --headless-check --data-dir $SmokeData 2>&1 | Out-String
Write-Host "    $($check.Trim())"
if ($check -notmatch "OK") { throw "Frozen executable failed --headless-check" }

# 4. Portable ZIP
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Get-ChildItem $OutDir -File | Remove-Item -Force
$ZipName = "AutoCorrect-Desktop-$FullVersion-win64-portable.zip"
$ZipPath = Join-Path $OutDir $ZipName
Compress-Archive -Path (Join-Path $AppDir "*") -DestinationPath $ZipPath -CompressionLevel Optimal

# 5. Inno Setup installer
$SetupName = "AutoCorrect-Desktop-$FullVersion-win64-setup.exe"
$SetupPath = Join-Path $OutDir $SetupName
if (-not $SkipInstaller) {
    $iscc = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($iscc) {
        & $iscc /Q "/DMyAppVersion=$Version" "/DMyChannel=$Channel" (Join-Path $PSScriptRoot "windows_installer.iss")
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed" }
    } else {
        Write-Warning "ISCC.exe not found — skipping Setup.exe (portable ZIP still produced)."
    }
}

# 6. Hashes + manifest (installers + individually downloadable domain packs)
$artifacts = Get-ChildItem $OutDir -File | Where-Object { $_.Extension -in ".zip", ".exe" }
$resManifest = Get-Content (Join-Path $Root "resources\en_base\manifest.json") -Raw | ConvertFrom-Json
$manifest = [ordered]@{
    product   = "AutoCorrect Desktop"
    version   = $Version
    channel   = $Channel
    full_version = $FullVersion
    platform  = "win64"
    built_at  = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    code_signed = $false
    resources = [ordered]@{
        bundle_version = $resManifest.version
        schema_version = $resManifest.schema_version
        word_count     = $resManifest.word_count
    }
    artifacts = @()
    packs     = @()
}
$sumsLines = @()
foreach ($a in $artifacts) {
    $hash = (Get-FileHash $a.FullName -Algorithm SHA256).Hash.ToLower()
    $kind = if ($a.Extension -eq ".exe") { "installer" } else { "portable" }
    $manifest.artifacts += [ordered]@{
        kind = $kind; file = $a.Name; size_bytes = $a.Length; sha256 = $hash
    }
    $sumsLines += "$hash  $($a.Name)"
}
$PacksOut = Join-Path $OutDir "packs"
New-Item -ItemType Directory -Force -Path $PacksOut | Out-Null
foreach ($p in Get-ChildItem (Join-Path $Root "resources\en_base\packs") -Filter "*.pack.json") {
    Copy-Item $p.FullName $PacksOut -Force
    $pj = Get-Content $p.FullName -Raw | ConvertFrom-Json
    $hash = (Get-FileHash $p.FullName -Algorithm SHA256).Hash.ToLower()
    $manifest.packs += [ordered]@{
        id = $pj.pack_id; version = $pj.version; file = $p.Name; size_bytes = $p.Length; sha256 = $hash
        word_count = @($pj.words.PSObject.Properties).Count; direct_typo_count = @($pj.direct_typos.PSObject.Properties).Count
    }
    $sumsLines += "$hash  packs/$($p.Name)"
}
$sumsLines | Set-Content -Path (Join-Path $OutDir "SHA256SUMS.txt") -Encoding ascii
# UTF-8 WITHOUT a BOM: Windows PowerShell's `-Encoding utf8` prepends one, which
# makes the public manifest invalid for strict JSON parsers.
[IO.File]::WriteAllText(
    (Join-Path $OutDir "release-manifest.json"),
    (($manifest | ConvertTo-Json -Depth 4) + "`n"),
    (New-Object System.Text.UTF8Encoding($false))
)

Write-Host ""
Write-Host "==> Artifacts" -ForegroundColor Green
$manifest.artifacts | ForEach-Object { Write-Host ("    {0,-60} {1,10:N0} bytes  {2}" -f $_.file, $_.size_bytes, $_.sha256) }

# 7. Publish to site
if (-not $SkipPublish) {
    New-Item -ItemType Directory -Force -Path $PublishDir | Out-Null
    Get-ChildItem $PublishDir -File -Filter "AutoCorrect-Desktop-*" | Remove-Item -Force
    Copy-Item (Join-Path $OutDir "*") $PublishDir -Recurse -Force
    Write-Host "==> Published to $PublishDir" -ForegroundColor Green
}
