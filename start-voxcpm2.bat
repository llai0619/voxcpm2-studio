@echo off
setlocal
chcp 65001 >nul
title VoxCPM2 Studio

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-voxcpm2.ps1" %*
set "VOXCPM_EXIT=%ERRORLEVEL%"

echo.
if not "%VOXCPM_EXIT%"=="0" echo [錯誤] 啟動失敗，錯誤碼：%VOXCPM_EXIT%
pause
exit /b %VOXCPM_EXIT%
