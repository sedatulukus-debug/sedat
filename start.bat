@echo off
title Testo 174T - Analiz Sistemi
chcp 65001 >nul 2>&1

:: Kurulum kontrolü
if not exist "venv\Scripts\python.exe" (
    echo  HATA: Kurulum yapilmamis!
    echo  Lutfen once install.bat dosyasini calistirin.
    echo.
    pause
    exit /b 1
)

echo.
echo  ============================================
echo   Testo 174T Olcum Analiz Sistemi
echo  ============================================
echo.
echo   Uygulama baslatiliyor...
echo   Adres: http://127.0.0.1:5000
echo.
echo   Kapatmak icin bu pencereyi kapatin (CTRL+C)
echo  --------------------------------------------
echo.

:: Tarayıcıyı 2 saniye sonra aç (arka planda)
start "" /B cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:5000"

:: Flask'ı başlat (ön planda kalır)
venv\Scripts\python app.py

pause
