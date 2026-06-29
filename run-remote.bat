@echo off
title MySpotify - Home Remote

REM ============================================================================
REM  MySpotify - Home Remote (one-click)
REM
REM  Same as run-standalone, but ALSO lets your phone (or another device) on the
REM  SAME Wi-Fi connect to this PC. On startup it prints a LAN address and a PIN:
REM
REM    In the phone app: Login -> "Connect to a home server" -> pick this PC
REM    (or type the address) -> enter the PIN.
REM
REM  FIRST RUN: Windows may pop up a Firewall prompt - click "Allow access" on
REM  Private networks, otherwise your phone won't be able to reach this PC.
REM
REM  TO QUIT: close this window or press Ctrl+C.
REM ============================================================================

set "MYSPOTIFY_REMOTE=1"
call "%~dp0run-standalone.bat"
