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
    # Path to an ffmpeg.exe to bundle. Defaults to the one on PATH.
    [string]$FfmpegPath
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
$vendorDir = Join-Path $backend "vendor\ffmpeg\win"
$vendorFfmpeg = Join-Path $vendorDir "ffmpeg.exe"
if (-not (Test-Path $vendorFfmpeg)) {
    if (-not $FfmpegPath) {
        $cmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
        if ($cmd) { $FfmpegPath = $cmd.Source }
    }
    if ($FfmpegPath -and (Test-Path $FfmpegPath)) {
        New-Item -ItemType Directory -Force -Path $vendorDir | Out-Null
        Copy-Item $FfmpegPath $vendorFfmpeg
        $mb = [math]::Round((Get-Item $vendorFfmpeg).Length / 1MB)
        Write-Host "[build] Vendored ffmpeg ($mb MB) from $FfmpegPath" -ForegroundColor Green
        if ($mb -gt 120) {
            Write-Host "[build] NOTE: that's a 'full' ffmpeg. For a smaller download, drop a" -ForegroundColor DarkYellow
            Write-Host "        'release-essentials' ffmpeg.exe into $vendorDir and rebuild." -ForegroundColor DarkYellow
        }
    } else {
        Write-Host "[build] WARNING: no ffmpeg found to bundle. The app will build but" -ForegroundColor Yellow
        Write-Host "        playback will fail. Install one (winget install Gyan.FFmpeg)" -ForegroundColor Yellow
        Write-Host "        or pass -FfmpegPath <path-to-ffmpeg.exe>, then rebuild." -ForegroundColor Yellow
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
