@echo off
title Testo 174T - Analiz Sistemi

:: Kurulum kontrolu
if not exist "venv\Scripts\python.exe" (
    echo  HATA: Kurulum yapilmamis^^!
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
echo   Sunucu baslatiliyor: http://127.0.0.1:5000
echo   Tarayici otomatik acilacak...
echo   Kapatmak icin bu pencereyi kapatin (CTRL+C)
echo  --------------------------------------------
echo.

:: Tarayiciyi 2 saniye sonra ac
start "" /B cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:5000"

:: Flask baslatiliyor
venv\Scripts\python app.py

pause
