<#
.SYNOPSIS
    Assemble and publish all five official TypenApp GitHub repositories:
      - https://github.com/TypenApp/.github
      - https://github.com/TypenApp/typen
      - https://github.com/TypenApp/language-data
      - https://github.com/TypenApp/model-resources
      - https://github.com/TypenApp/docs

.PARAMETER Org
    GitHub organisation name (default: "TypenApp").

.PARAMETER OutDir
    Staging directory for the assembled repository trees (default: "dist/org-repos").

.PARAMETER DryRun
    Assemble and initialize git repositories locally without pushing to GitHub.
#>
[CmdletBinding()]
param(
    [string]$Org = "TypenApp",
    [string]$OutDir = "dist/org-repos",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

Write-Host "==> 1. Syncing Markdown documentation from site/src/data/docs.ts" -ForegroundColor Cyan
python -m pipeline.sync_docs
if ($LASTEXITCODE -ne 0) { throw "pipeline.sync_docs failed" }

Write-Host "==> 2. Assembling and publishing $Org repositories" -ForegroundColor Cyan
$pyArgs = @("scripts/build_org_repos.py", "--out-dir", $OutDir, "--org", $Org)
if ($DryRun) {
    $pyArgs += "--dry-run"
} else {
    $pyArgs += "--publish"
}
python @pyArgs
if ($LASTEXITCODE -ne 0) { throw "scripts/build_org_repos.py failed" }
