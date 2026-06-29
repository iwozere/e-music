<#
.SYNOPSIS
  Build the MySpotify Standalone Edition into a self-contained Windows folder.

.DESCRIPTION
  Produces dist/MySpotify/ - a folder with MySpotify.exe and everything it needs
  (Python runtime, dependencies, web UI, and ffmpeg). The target PC needs NOTHING
  preinstalled. Zip the folder to distribute it. See docs/features-v7.md (Phase 4).

.NOTES
  Run from the repository root:  ./build-standalone.ps1
#>
[CmdletBinding()]
param(
    # Path to a specific ffmpeg.exe to bundle. If omitted, the essentials build is downloaded.
    [string]$FfmpegPath,
    # Where to fetch a small ffmpeg from when none is vendored/provided.
    [string]$FfmpegEssentialsUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
)

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
$backend = Join-Path $repo "backend"
$py = Join-Path $repo ".venv\Scripts\python.exe"

Write-Host "== MySpotify Standalone build ==" -ForegroundColor Cyan

if (-not (Test-Path $py)) {
    throw "Virtual environment not found at $py. Create it and install backend/requirements.txt first."
}

# 1. Ensure PyInstaller is available.
& $py -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[build] Installing PyInstaller..." -ForegroundColor Yellow
    & $py -m pip install pyinstaller
}

# 2. Vendor ffmpeg so playback works without a system install.
#    Priority: explicit -FfmpegPath > already-vendored > download the small essentials build.
$vendorDir = Join-Path $backend "vendor\ffmpeg\win"
$vendorFfmpeg = Join-Path $vendorDir "ffmpeg.exe"
if (Test-Path $vendorFfmpeg) {
    $mb = [math]::Round((Get-Item $vendorFfmpeg).Length / 1MB, 1)
    Write-Host "[build] Using vendored ffmpeg ($mb MB) at $vendorFfmpeg" -ForegroundColor Green
}
elseif ($FfmpegPath -and (Test-Path $FfmpegPath)) {
    New-Item -ItemType Directory -Force -Path $vendorDir | Out-Null
    Copy-Item $FfmpegPath $vendorFfmpeg
    $mb = [math]::Round((Get-Item $vendorFfmpeg).Length / 1MB, 1)
    Write-Host "[build] Vendored ffmpeg ($mb MB) from $FfmpegPath" -ForegroundColor Green
}
else {
    Write-Host "[build] Downloading ffmpeg (release-essentials)..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $vendorDir | Out-Null
    $zip = Join-Path $env:TEMP "ffmpeg-essentials.zip"
    $tmp = Join-Path $env:TEMP "ffmpeg-ess-extract"
    try {
        Invoke-WebRequest -Uri $FfmpegEssentialsUrl -OutFile $zip -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        $src = Get-ChildItem -Path $tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1
        Copy-Item $src.FullName $vendorFfmpeg -Force
        $mb = [math]::Round((Get-Item $vendorFfmpeg).Length / 1MB, 1)
        Write-Host "[build] Vendored essentials ffmpeg ($mb MB)" -ForegroundColor Green
    } catch {
        Write-Host "[build] WARNING: ffmpeg download failed ($_). The app will build but" -ForegroundColor Yellow
        Write-Host "        playback will fail. Pass -FfmpegPath <ffmpeg.exe> or drop one at" -ForegroundColor Yellow
        Write-Host "        $vendorFfmpeg, then rebuild." -ForegroundColor Yellow
    }
}

# 3. Freeze. Run from backend/ so the spec's relative paths resolve.
Write-Host "[build] Running PyInstaller (this can take several minutes)..." -ForegroundColor Cyan
Push-Location $backend
try {
    & $py -m PyInstaller "desktop.spec" --noconfirm --distpath (Join-Path $repo "dist") --workpath (Join-Path $repo "build\pyinstaller")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

$out = Join-Path $repo "dist\MySpotify"
Write-Host ""
Write-Host "== Build complete ==" -ForegroundColor Green
Write-Host "  Folder : $out"
Write-Host "  Run    : `"$out\MySpotify.exe`""
Write-Host "  Ship it: zip the MySpotify folder and copy it to any Windows PC."
