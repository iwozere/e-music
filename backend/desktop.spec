# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for MySpotify - Standalone Edition (docs/features-v7.md Phase 4).

One-folder build (not one-file, so the bundled ffmpeg isn't re-extracted every launch).
Build from the backend/ directory:

    ../.venv/Scripts/python.exe -m PyInstaller desktop.spec --noconfirm

Output: dist/MySpotify/  (run dist/MySpotify/MySpotify.exe)
"""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas: list = []
binaries: list = []
hiddenimports: list = []

# Heavy / dynamic-import packages: pull in submodules + data files so they survive freezing.
# yt_dlp in particular loads its extractors dynamically and must be collected wholesale.
for _pkg in (
    "yt_dlp",
    "ytmusicapi",
    "uvicorn",
    "groq",
    "google.genai",
    "google.auth",
    "email_validator",
    "passlib",   # handlers (e.g. passlib.handlers.bcrypt) are imported via a runtime registry
    "bcrypt",
    "webview",   # pywebview: native window; ships the WebView2 loader DLLs as package data
    "clr_loader",
):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# pythonnet's import name is 'clr'; ensure it survives freezing for the WebView2 backend.
hiddenimports += ["clr"]

# Our own package: routers/services are sometimes imported inside functions.
hiddenimports += collect_submodules("app")

# Web UI assets ship next to the backend (app/main.py resolves static/ relative to __file__).
datas += [("app/static", "app/static")]

# Vendored ffmpeg, if present (populated by build-standalone.ps1). Lands at _internal/ffmpeg/.
_ffmpeg = os.path.join("vendor", "ffmpeg", "win", "ffmpeg.exe")
if os.path.exists(_ffmpeg):
    binaries += [(_ffmpeg, "ffmpeg")]
    print(f"[spec] bundling ffmpeg from {_ffmpeg}")
else:
    print(f"[spec] WARNING: {_ffmpeg} not found - the build will have no playback engine")

a = Analysis(
    ["app/desktop.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PySide6", "PyQt5"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MySpotify",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # keep the console so the launcher banner + logs are visible
    # No custom icon: favicon.png isn't an .ico and converting needs Pillow. Add an .ico later.
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="MySpotify",
)
