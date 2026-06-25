@echo off
cd /d "%~dp0"
echo ============================================ > tani_log.txt
echo Terkon Veresiye - Tani Raporu >> tani_log.txt
echo Tarih: %date% %time% >> tani_log.txt
echo ============================================ >> tani_log.txt
echo. >> tani_log.txt

echo [Klasor] >> tani_log.txt
dir /b "%~dp0" >> tani_log.txt
echo. >> tani_log.txt

echo [Data klasoru] >> tani_log.txt
dir /b "%~dp0Data\" >> tani_log.txt 2>&1
echo. >> tani_log.txt

echo [Windows surumu] >> tani_log.txt
ver >> tani_log.txt
echo. >> tani_log.txt

echo [DLL kontrol] >> tani_log.txt
for %%f in (ace32.dll adsloc32.dll axcws32.dll exasql.dll) do (
    if exist "%%f" (echo %%f: MEVCUT >> tani_log.txt) else (echo %%f: EKSIK! >> tani_log.txt)
)
echo. >> tani_log.txt

echo [Veritabani] >> tani_log.txt
if exist "Data\Data.edb" (echo Data\Data.edb: MEVCUT >> tani_log.txt) else (echo Data\Data.edb: EKSIK! >> tani_log.txt)
echo. >> tani_log.txt

echo [Program calistiriliyor - v2 patch...] >> tani_log.txt
Veresiye.exe
set EXIT_CODE=%errorlevel%
echo Program cikis kodu: %EXIT_CODE% >> tani_log.txt

type tani_log.txt
echo.
pause
