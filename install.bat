@echo off
title Testo 174T - Kurulum
echo.
echo  ============================================
echo   Testo 174T Olcum Analiz Sistemi - Kurulum
echo  ============================================
echo.

:: Python kontrolu
python --version >nul 2>&1
if errorlevel 1 (
    echo  HATA: Python bulunamadi^^!
    echo  Lutfen https://python.org adresinden Python 3.9+ indirin.
    echo  Kurulum sirasinda "Add Python to PATH" secenegini isaretleyin.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  Python bulundu: %PYVER%
echo.

:: Sanal ortam
echo  [1/3] Sanal ortam olusturuluyor...
if exist venv (
    echo        Mevcut sanal ortam kullanilacak.
) else (
    python -m venv venv
    if errorlevel 1 (
        echo  HATA: Sanal ortam olusturulamadi.
        pause
        exit /b 1
    )
)

:: pip guncelle (python -m pip kullan, dogrudan pip degil)
venv\Scripts\python.exe -m pip install --upgrade pip --quiet 2>nul

:: Paketleri kur
echo  [2/3] Gerekli paketler yukleniyor...
venv\Scripts\python.exe -m pip install flask pdfplumber --quiet
if errorlevel 1 (
    echo  HATA: Paketler yuklenemedi. Internet baglantinizi kontrol edin.
    pause
    exit /b 1
)

:: Klasor
echo  [3/3] Klasor yapisi hazirlaniyor...
if not exist knowledge_base mkdir knowledge_base

echo.
echo  ============================================
echo   Kurulum tamamlandi^^!
echo  ============================================
echo.
echo   Programi baslatmak icin: start.bat
echo   EXE olusturmak icin    : build.bat
echo.
pause
