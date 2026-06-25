@echo off
chcp 65001 >nul 2>&1
title Terkon Veresiye - Windows 11 Kurulum

echo ========================================
echo   Terkon Veresiye - Windows 11 Kurulum
echo ========================================
echo.

:: Yonetici yetkisi kontrol
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Yonetici yetkisi gerekli. Yukaridan onayin...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

:: PowerShell scripti calistir
powershell -ExecutionPolicy Bypass -File "%~dp0Kur.ps1"

if %errorLevel% neq 0 (
    echo.
    echo HATA: Kurulum basarisiz oldu!
    echo PowerShell scripti manuel calistirin: Kur.ps1
    pause
    exit /b 1
)
