@echo off
rem Ainara AI Companion Framework Project
rem Copyright (C) 2025 Ruben Gomez - khromalabs.org
rem Dual-licensed: LGPL-3.0 / Commercial (see LICENSE_LGPL3.txt)

rem Thin launcher for scripts\bootstrap.py (Windows).
rem Only locates a suitable Python interpreter; all logic lives in bootstrap.py.

setlocal
set "SCRIPT=%~dp0bootstrap.py"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%SCRIPT%" %*
    exit /b %errorlevel%
)

where python >nul 2>nul
if %errorlevel%==0 (
    python "%SCRIPT%" %*
    exit /b %errorlevel%
)

echo bootstrap: no Python interpreter found (Python 3.12 required) 1>&2
exit /b 1
