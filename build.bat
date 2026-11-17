@echo off
setlocal
title Secure Local Video Server V2.1.0 Build Tool

rem 用 Python 3.10（PyInstaller / Flask 装在这上面；py 默认的 3.15 里没有）
set "PYTHON=py -3.10"
set "APPNAME=SecureLocalVideoServer"

echo.
echo ==========================================
echo Building %APPNAME% V2.1.0...
echo ==========================================
echo.

if not exist cloudflared.exe (
    echo [ERROR] cloudflared.exe not found in %CD%
    echo         Download it from https://github.com/cloudflare/cloudflared/releases
    pause
    exit /b 1
)

%PYTHON% -m PyInstaller -y -w --clean ^
--onedir ^
--name %APPNAME% ^
-i %APPNAME%.ico ^
--version-file version_info.txt ^
--add-binary "cloudflared.exe;." ^
server_gui_v2.py

if errorlevel 1 (
    echo.
    echo ==========================================
    echo BUILD FAILED!
    echo ==========================================
    pause
    exit /b 1
)

echo.
echo ==========================================
echo BUILD SUCCESS!
echo EXE:
echo dist\%APPNAME%\%APPNAME%.exe
echo ==========================================
echo.

pause
