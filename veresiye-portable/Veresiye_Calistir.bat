@echo off
cd /d "%~dp0"

:: Windows XP SP3 uyumluluk simi - DEP'i devre disi birakir (packer icin gerekli)
:: Bu ayar sadece Veresiye.exe icin gecerlidir, sistemi etkilemez
reg add "HKCU\SOFTWARE\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers" /v "%~dp0Veresiye.exe" /t REG_SZ /d "~ WINXPSP3" /f >nul 2>&1

:: Programi baslat
start "" "%~dp0Veresiye.exe"
