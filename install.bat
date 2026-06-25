@echo off
title Testo 174T - Kurulum
chcp 65001 >nul 2>&1
echo.
echo  ============================================
echo   Testo 174T Olcum Analiz Sistemi - Kurulum
echo  ============================================
echo.

:: Python kontrolü
python --version >nul 2>&1
if errorlevel 1 (
    echo  HATA: Python bulunamadi!
    echo  Lutfen https://python.org adresinden Python 3.9+ indirin.
    echo  Kurulum sirasinda "Add Python to PATH" secenegini isaretleyin.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  Python bulundu: %PYVER%
echo.

:: Sanal ortam oluştur
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

:: Paketleri kur
echo  [2/3] Gerekli paketler yukleniyor...
venv\Scripts\pip install --upgrade pip --quiet
venv\Scripts\pip install flask pdfplumber --quiet
if errorlevel 1 (
    echo  HATA: Paketler yuklenemedi. Internet baglantinizi kontrol edin.
    pause
    exit /b 1
)

:: Knowledge base klasörü
echo  [3/3] Klasor yapisi hazirlaniyor...
if not exist knowledge_base mkdir knowledge_base

echo.
echo  ============================================
echo   Kurulum tamamlandi!
echo  ============================================
echo.
echo   Programi baslatmak icin:
echo   - start.bat dosyasini cift tiklayin
echo.
pause
