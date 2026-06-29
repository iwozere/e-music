<#
.SYNOPSIS
  Build the MySpotify Windows installer (MySpotify-Setup-x.y.z.exe) with Inno Setup.

.DESCRIPTION
  Wraps the self-contained dist\MySpotify\ folder (from build-standalone.ps1) into a
  single per-user installer that needs no admin rights and no prerequisites on the
  target PC. Output lands in dist\installer\. See docs/features-v7.md (Phase 5).

  This is a LOCAL build - nothing is uploaded anywhere. Distribute the resulting
  Setup .exe yourself.

.NOTES
  Run from the repository root:  ./build-installer.ps1
  Requires Inno Setup 6 (winget install JRSoftware.InnoSetup).
#>
[CmdletBinding()]
param(
    # Build the standalone folder first if it's missing (or pass -Rebuild to force it).
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
$distApp = Join-Path $repo "dist\MySpotify"
$iss = Join-Path $repo "MySpotify.iss"

Write-Host "== MySpotify installer build ==" -ForegroundColor Cyan

# 1. Locate the Inno Setup compiler.
$iscc = $null
$cmd = Get-Command ISCC -ErrorAction SilentlyContinue
if ($cmd) { $iscc = $cmd.Source }
if (-not $iscc) {
    foreach ($p in @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"   # winget user-scope install
    )) {
        if (Test-Path $p) { $iscc = $p; break }
    }
}
if (-not $iscc) {
    Write-Host "[installer] Inno Setup (ISCC.exe) was not found." -ForegroundColor Yellow
    Write-Host "            Install it once, then re-run this script:" -ForegroundColor Yellow
    Write-Host "                winget install JRSoftware.InnoSetup" -ForegroundColor Yellow
    throw "Inno Setup compiler not found."
}
Write-Host "[installer] Using ISCC: $iscc"

# 2. Ensure the standalone folder exists (build it if needed).
if ($Rebuild -or -not (Test-Path (Join-Path $distApp "MySpotify.exe"))) {
    Write-Host "[installer] Building the standalone folder first..." -ForegroundColor Cyan
    & (Join-Path $repo "build-standalone.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Standalone build failed." }
}

# 3. Compile the installer.
Write-Host "[installer] Compiling $iss ..." -ForegroundColor Cyan
& $iscc $iss
if ($LASTEXITCODE -ne 0) { throw "ISCC failed with exit code $LASTEXITCODE" }

$out = Get-ChildItem (Join-Path $repo "dist\installer") -Filter "MySpotify-Setup-*.exe" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
Write-Host ""
Write-Host "== Installer ready ==" -ForegroundColor Green
if ($out) {
    $mb = [math]::Round($out.Length / 1MB, 1)
    Write-Host "  File : $($out.FullName) ($mb MB)"
    Write-Host "  Ship : send this single .exe to any Windows PC and run it (no admin needed)."
}
