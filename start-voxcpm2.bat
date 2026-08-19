@echo off
setlocal
chcp 65001 >nul
title VoxCPM2 Studio

set "VOXCPM_SERVER=llai@172.16.0.103"
set "LOCAL_PORT=8808"
set "REMOTE_PORT=8808"
set "STUDIO_URL=http://127.0.0.1:%LOCAL_PORT%"

where ssh >nul 2>&1
if errorlevel 1 (
    echo [錯誤] 找不到 Windows SSH 用戶端。
    echo 請在「選用功能」安裝 OpenSSH Client 後再試一次。
    pause
    exit /b 1
)

netstat -ano | findstr /R /C:":%LOCAL_PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [錯誤] 本機連接埠 %LOCAL_PORT% 已被使用。
    echo 請關閉先前的 SSH tunnel 或使用該既有連線。
    pause
    exit /b 1
)

echo ==================================================
echo   VoxCPM2 Studio 自動啟動
echo ==================================================
echo.
echo 伺服器：%VOXCPM_SERVER%
echo 網址：  %STUDIO_URL%
echo.
echo 請輸入伺服器密碼。啟動後請保持此視窗開啟。
echo 按 Ctrl+C 可以停止服務及 SSH tunnel。
echo.

start "" /b powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden ^
    -File "%~dp0scripts\wait-and-open.ps1" -Url "%STUDIO_URL%" -Port %LOCAL_PORT%

ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -t ^
    -L %LOCAL_PORT%:127.0.0.1:%REMOTE_PORT% ^
    %VOXCPM_SERVER% ^
    "cd ~/voxcpm2-studio && git pull --ff-only && bash scripts/start-server.sh"

set "SSH_EXIT=%ERRORLEVEL%"
echo.
if not "%SSH_EXIT%"=="0" (
    echo [錯誤] VoxCPM2 或 SSH 連線已中止，錯誤碼：%SSH_EXIT%
) else (
    echo VoxCPM2 Studio 已停止。
)
pause
exit /b %SSH_EXIT%
