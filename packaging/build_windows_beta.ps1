<#
.SYNOPSIS
    Build the Typen Windows distributables. Windows is the stable platform, so
    its files are versioned plainly (Typen-1.2.0-win64-setup.exe); the -Channel
    suffix only names the GitHub Release (v1.2.0-beta.4) that hosts them
    alongside the macOS and Linux betas.

.DESCRIPTION
    1. Generates the application icon.
    2. Runs PyInstaller (one-folder) via packaging/autocorrect.spec  -> dist/AutoCorrectDesktop/
    3. Smoke-tests the frozen executable (--version, --headless-check).
    4. Zips the folder as a portable build                              -> dist/installer/*.zip
    5. Compiles the Inno Setup installer (if ISCC.exe is available)    -> dist/installer/*-setup.exe
    6. Writes SHA-256 sums + release-manifest-win64.json next to the artifacts and
       refreshes site/src/data/release-manifest.json (the only thing the site needs).
       Binaries are never committed: push a `v<version>-<channel>` tag and
       .github/workflows/release.yml builds every platform and attaches the
       installers to a GitHub Release, which the site links to.

.PARAMETER Channel
    Suffix of the release tag this build is published under, e.g. "beta.3"
    (tag v<version>-beta.3). Not part of the Windows file names or version.

.EXAMPLE
    pwsh packaging/build_windows_beta.ps1 -Channel beta.1
#>
[CmdletBinding()]
param(
    [string]$Channel = "beta.3",
    [switch]$SkipInstaller,
    [switch]$SkipPublish
)

<#
  Authenticode signing is opt-in. When these environment variables are set the
  frozen executable (before packaging) and the Setup.exe (after Inno) are signed
  with signtool and RFC-3161 timestamped; otherwise the build stays unsigned and
  release-manifest.json records code_signed=false (the site then shows the
  SmartScreen notice).

    AC_WIN_SIGN_PFX         path to the .pfx (or omit and use AC_WIN_SIGN_SHA1 for a
                            cert in the current user's store / HSM-backed EV token)
    AC_WIN_SIGN_PFX_PASSWORD
    AC_WIN_SIGN_SHA1        certificate thumbprint (alternative to the .pfx)
    AC_WIN_SIGN_TIMESTAMP   RFC-3161 URL (default http://timestamp.digicert.com)
#>
$SignPfx = $env:AC_WIN_SIGN_PFX
$SignSha1 = $env:AC_WIN_SIGN_SHA1
$SignTimestamp = if ($env:AC_WIN_SIGN_TIMESTAMP) { $env:AC_WIN_SIGN_TIMESTAMP } else { "http://timestamp.digicert.com" }
$CodeSigned = $false

function Find-SignTool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $kits = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (Test-Path $kits) {
        $hit = Get-ChildItem $kits -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "\\x64\\" } | Sort-Object FullName -Descending | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

function Invoke-Sign([string]$Path) {
    if (-not ($SignPfx -or $SignSha1)) { return $false }
    $signtool = Find-SignTool
    if (-not $signtool) { throw "Signing requested but signtool.exe was not found (install the Windows 10/11 SDK)." }
    $args = @("sign", "/fd", "SHA256", "/td", "SHA256", "/tr", $SignTimestamp, "/d", "Typen")
    if ($SignPfx) {
        $args += @("/f", $SignPfx)
        if ($env:AC_WIN_SIGN_PFX_PASSWORD) { $args += @("/p", $env:AC_WIN_SIGN_PFX_PASSWORD) }
    } else {
        $args += @("/sha1", $SignSha1)
    }
    & $signtool @args $Path
    if ($LASTEXITCODE -ne 0) { throw "signtool failed for $Path" }
    & $signtool verify /pa /q $Path
    if ($LASTEXITCODE -ne 0) { throw "signature verification failed for $Path" }
    Write-Host "    signed $([IO.Path]::GetFileName($Path))" -ForegroundColor Green
    return $true
}

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$Version = (python -c "import sys; sys.path.insert(0,'src'); from autocorrect.version import APP_VERSION; print(APP_VERSION)").Trim()
# The Windows build is stable: its version and file names carry no channel
# suffix. The tag of the GitHub Release that hosts it still does.
$FullVersion = $Version
$ReleaseTag = "v$Version-$Channel"
$DistDir = Join-Path $Root "dist"
$AppDir = Join-Path $DistDir "AutoCorrectDesktop"
$OutDir = Join-Path $DistDir "installer"

Write-Host "==> Typen $FullVersion (win64, release $ReleaseTag)" -ForegroundColor Cyan

# 0. Tooling
python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) { python -m pip install --quiet pyinstaller }
# The Settings window is PySide6/QML; without it the frozen app would ship the tkinter fallback.
python -c "import PySide6.QtQml, comtypes" 2>$null
if ($LASTEXITCODE -ne 0) { python -m pip install --quiet -e ".[ui]" "comtypes>=1.4.0" }

# 1. Icon
python (Join-Path $PSScriptRoot "make_icon.py")

# 2. PyInstaller one-folder
if (Test-Path $AppDir) { Remove-Item $AppDir -Recurse -Force }
python -m PyInstaller --noconfirm --clean --distpath $DistDir --workpath (Join-Path $DistDir "build") (Join-Path $PSScriptRoot "autocorrect.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
# Licence gate: no GPLv3-only Qt module may ship (see ui/lgpl_compliance.py).
$env:PYTHONPATH = "src"
python -c "import sys; from pathlib import Path; from autocorrect.ui.lgpl_compliance import scan_distribution_dir_for_gpl_binaries as s; bad = s(Path(sys.argv[1])); print('    GPL scan: ' + ('clean' if not bad else str(bad))); sys.exit(1 if bad else 0)" $AppDir
$gplOk = ($LASTEXITCODE -eq 0)
Remove-Item Env:PYTHONPATH
if (-not $gplOk) { throw "GPLv3-only Qt binaries found in the frozen build" }

# 2b. Authenticode-sign the frozen executable (no-op unless AC_WIN_SIGN_* is set)
$Exe = Join-Path $AppDir "AutoCorrectDesktop.exe"
$CodeSigned = Invoke-Sign $Exe
if (-not $CodeSigned) { Write-Host "    AC_WIN_SIGN_* not set: building UNSIGNED (SmartScreen will warn)" -ForegroundColor Yellow }

# 3. Smoke test the frozen binary
$SmokeData = Join-Path $env:TEMP "autocorrect_beta_smoke"
if (Test-Path $SmokeData) { Remove-Item $SmokeData -Recurse -Force }
$ver = & $Exe --version 2>&1 | Out-String
Write-Host "    $($ver.Trim())"
$check = & $Exe --headless-check --data-dir $SmokeData 2>&1 | Out-String
Write-Host "    $($check.Trim())"
if ($check -notmatch "OK") { throw "Frozen executable failed --headless-check" }
# The Settings window must come up as the QML UI, not the tkinter fallback: start it on the
# offscreen Qt platform, give it a few seconds, and fail if it died or logged the fallback.
$env:QT_QPA_PLATFORM = "offscreen"
$ui = Start-Process -FilePath $Exe -ArgumentList "--settings", "--data-dir", $SmokeData -PassThru
Start-Sleep -Seconds 8
$uiAlive = -not $ui.HasExited
if ($uiAlive) { Stop-Process -Id $ui.Id -Force }
Remove-Item Env:QT_QPA_PLATFORM
$uiLog = Join-Path $SmokeData "logs\typen.log"
$uiLogText = if (Test-Path $uiLog) { Get-Content $uiLog -Raw } else { "" }
if (-not $uiAlive) { throw "Frozen Settings window exited early (see $uiLog)" }
if ($uiLogText -match "native fallback") { throw "Frozen Settings window fell back to tkinter: PySide6/QML is not bundled correctly (see $uiLog)" }
Write-Host "    Settings window (QML) OK"

# 4. Portable ZIP
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Get-ChildItem $OutDir -File | Remove-Item -Force
$ZipName = "Typen-$FullVersion-win64-portable.zip"
$ZipPath = Join-Path $OutDir $ZipName
Compress-Archive -Path (Join-Path $AppDir "*") -DestinationPath $ZipPath -CompressionLevel Optimal

# 5. Inno Setup installer
$SetupName = "Typen-$FullVersion-win64-setup.exe"
$SetupPath = Join-Path $OutDir $SetupName
if (-not $SkipInstaller) {
    $iscc = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($iscc) {
        & $iscc /Q "/DMyAppVersion=$Version" "/DMyChannel=stable" (Join-Path $PSScriptRoot "windows_installer.iss")
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed" }
        if ($CodeSigned) { [void](Invoke-Sign $SetupPath) }
    } else {
        Write-Warning "ISCC.exe not found — skipping Setup.exe (portable ZIP still produced)."
    }
}

# 6. Hashes + manifest (installers + individually downloadable domain packs)
$artifacts = Get-ChildItem $OutDir -File | Where-Object { $_.Extension -in ".zip", ".exe" }
$resManifest = Get-Content (Join-Path $Root "resources\en_base\manifest.json") -Raw | ConvertFrom-Json
$manifest = [ordered]@{
    product   = "Typen"
    version   = $Version
    channel   = "stable"
    full_version = $FullVersion
    release_tag = $ReleaseTag
    platform  = "win64"
    built_at  = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    code_signed = $CodeSigned
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
    (Join-Path $OutDir "release-manifest-win64.json"),
    (($manifest | ConvertTo-Json -Depth 4) + "`n"),
    (New-Object System.Text.UTF8Encoding($false))
)

Write-Host ""
Write-Host "==> Artifacts" -ForegroundColor Green
$manifest.artifacts | ForEach-Object { Write-Host ("    {0,-60} {1,10:N0} bytes  {2}" -f $_.file, $_.size_bytes, $_.sha256) }

# 7. Refresh the manifest the site reads (binaries stay in dist/installer; the
#    release workflow attaches them to the GitHub Release the site links to).
if (-not $SkipPublish) {
    python -m pipeline.merge_release_manifests --downloads $OutDir
    if ($LASTEXITCODE -ne 0) { throw "merge_release_manifests failed" }
    Write-Host "==> Artifacts in $OutDir; site manifest updated." -ForegroundColor Green
    Write-Host "    To publish: git tag $ReleaseTag && git push origin $ReleaseTag" -ForegroundColor Green
}
