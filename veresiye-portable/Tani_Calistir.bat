@echo off
:: Tani aracı - program neden acilmiyor? Log dosyasina yazar
cd /d "%~dp0"
echo ============================================ > tani_log.txt
echo Terkon Veresiye - Tani Raporu >> tani_log.txt
echo Tarih: %date% %time% >> tani_log.txt
echo ============================================ >> tani_log.txt
echo. >> tani_log.txt

echo [Klasor kontrol] >> tani_log.txt
dir /b "%~dp0" >> tani_log.txt
echo. >> tani_log.txt

echo [Data klasoru] >> tani_log.txt
dir /b "%~dp0Data\" >> tani_log.txt 2>&1
echo. >> tani_log.txt

echo [Windows surumu] >> tani_log.txt
ver >> tani_log.txt
echo. >> tani_log.txt

echo [32-bit DLL kontrol] >> tani_log.txt
for %%f in (ace32.dll adsloc32.dll axcws32.dll exasql.dll) do (
    if exist "%%f" (
        echo %%f: MEVCUT >> tani_log.txt
    ) else (
        echo %%f: EKSIK! >> tani_log.txt
    )
)
echo. >> tani_log.txt

echo [Veritabani kontrol] >> tani_log.txt
if exist "Data\Data.edb" (
    echo Data\Data.edb: MEVCUT >> tani_log.txt
) else (
    echo Data\Data.edb: EKSIK! >> tani_log.txt
)
echo. >> tani_log.txt

echo [Program calistiriliyor...] >> tani_log.txt
Veresiye.exe
set EXIT_CODE=%errorlevel%
echo Program cikis kodu: %EXIT_CODE% >> tani_log.txt
echo. >> tani_log.txt

if %EXIT_CODE% neq 0 (
    echo HATA: Program hata koduyla kapandi: %EXIT_CODE% >> tani_log.txt
) else (
    echo Program normal kapandi. >> tani_log.txt
)

echo. >> tani_log.txt
echo Tani tamamlandi. >> tani_log.txt
type tani_log.txt
echo.
echo Bu ekranin fotografini cekin veya tani_log.txt dosyasini gonderin.
pause
