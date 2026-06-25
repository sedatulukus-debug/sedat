@echo off
title Testo 174T - EXE Olusturuluyor
echo.
echo  ============================================
echo   Testo 174T - EXE Derleme
echo  ============================================
echo.

if not exist "venv\Scripts\python.exe" (
    echo  HATA: Once install.bat calistirin.
    pause & exit /b 1
)

echo  [1/3] PyInstaller yukleniyor...
venv\Scripts\pip install pyinstaller --quiet

echo  [2/3] EXE olusturuluyor (birkac dakika surebilir)...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

venv\Scripts\pyinstaller ^
    --onefile ^
    --noconsole ^
    --name "Testo174T" ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --hidden-import pdfplumber ^
    --hidden-import pdfminer ^
    --hidden-import pdfminer.high_level ^
    --hidden-import pdfminer.layout ^
    --hidden-import flask ^
    --hidden-import werkzeug ^
    app_launcher.py

if not exist "dist\Testo174T.exe" (
    echo  HATA: Derleme basarisiz.
    pause & exit /b 1
)

:: knowledge_base klasorunu dist yanina kopyala
if not exist "dist\knowledge_base" mkdir "dist\knowledge_base"

echo  [3/3] Masaustu kisayolu olusturuluyor...
set "EXE=%~dp0dist\Testo174T.exe"
set "WD=%~dp0dist"
set "LNK=%USERPROFILE%\Desktop\Testo 174T Analiz.lnk"

powershell -NoProfile -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut('%LNK%');$s.TargetPath='%EXE%';$s.WorkingDirectory='%WD%';$s.Description='Testo 174T Olcum Analiz Sistemi';$s.Save()"

echo.
echo  ============================================
echo   Tamamlandi^^!
echo.
echo   EXE konumu : dist\Testo174T.exe
echo   Masaustu kisayolu eklendi.
echo  ============================================
echo.
pause
