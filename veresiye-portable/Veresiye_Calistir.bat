@echo off
:: Veresiye programini dogru klasorden calistirir
:: Calisma dizinini exe'nin yanina ayarlar (veritabani bulunmasi icin)
cd /d "%~dp0"
start "" "%~dp0Veresiye.exe"
