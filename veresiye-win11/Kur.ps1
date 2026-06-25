#Requires -RunAsAdministrator
# Terkon Veresiye - Windows 11 Kurulum Scripti
# Calistirmak icin: Sag tik > "PowerShell ile Calistir" (Yonetici olarak)

$AppName    = "Terkon Veresiye"
$InstallDir = "C:\Program Files (x86)\Terkon\Veresiye"
$DataDir    = "$env:APPDATA\Terkon\Veresiye\Data"
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir     = Join-Path $ScriptDir "app"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  $AppName - Windows 11 Kurulum" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. Klasorleri olustur
Write-Host "[1/6] Klasorler olusturuluyor..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $DataDir    | Out-Null

# 2. Uygulama dosyalarini kopyala
Write-Host "[2/6] Dosyalar kopyalaniyor..." -ForegroundColor Yellow
Copy-Item -Path "$AppDir\*" -Destination $InstallDir -Recurse -Force

# 3. Veritabani dosyasini kullanici veri klasorune tasi (yazma izni icin)
Write-Host "[3/6] Veritabani dosyasi ayarlaniyor..." -ForegroundColor Yellow
$DbSource = "$InstallDir\Data\Data.edb"
$DbTarget = "$DataDir\Data.edb"
if ((Test-Path $DbSource) -and -not (Test-Path $DbTarget)) {
    Copy-Item -Path $DbSource -Destination $DbTarget -Force
}

# 4. adslocal.cfg'yi guncelle - log dizini olarak program klasorunu kullan
Write-Host "[4/6] Yapilandirma guncelleniyor..." -ForegroundColor Yellow
$cfgPath = "$InstallDir\adslocal.cfg"
(Get-Content $cfgPath) -replace 'ERROR_ASSERT_LOGS=.*', "ERROR_ASSERT_LOGS=$InstallDir\" |
    Set-Content $cfgPath

# 5. Masaustu kisayolu olustur
Write-Host "[5/6] Masaustu kisayolu olusturuluyor..." -ForegroundColor Yellow
$WsShell   = New-Object -ComObject WScript.Shell
$Shortcut  = $WsShell.CreateShortcut("$env:PUBLIC\Desktop\$AppName.lnk")
$Shortcut.TargetPath       = "$InstallDir\Veresiye.exe"
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Description      = $AppName
$Shortcut.Save()

# 6. Registry kaydi (Program Ekle/Kaldir icin)
Write-Host "[6/6] Registry kaydi yapiliyor..." -ForegroundColor Yellow
$RegPath = "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\TerkonVeresiye"
New-Item -Path $RegPath -Force | Out-Null
Set-ItemProperty -Path $RegPath -Name "DisplayName"      -Value $AppName
Set-ItemProperty -Path $RegPath -Name "DisplayVersion"   -Value "1.0"
Set-ItemProperty -Path $RegPath -Name "Publisher"        -Value "Terkon"
Set-ItemProperty -Path $RegPath -Name "InstallLocation"  -Value $InstallDir
Set-ItemProperty -Path $RegPath -Name "UninstallString"  -Value "rmdir /s /q `"$InstallDir`""

# Uyumluluk ayari - Windows 11'de XP uyumluluk modunu DEVRE DISI birak
$CompatRegPath = "HKCU:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
New-Item -Path $CompatRegPath -Force -ErrorAction SilentlyContinue | Out-Null
# Onceki uyumluluk modlarini temizle (varsa)
Remove-ItemProperty -Path $CompatRegPath -Name "$InstallDir\Veresiye.exe" -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Kurulum tamamlandi!" -ForegroundColor Green
Write-Host "  Konum: $InstallDir" -ForegroundColor Green
Write-Host "  Masaustuunden 'Terkon Veresiye'" -ForegroundColor Green
Write-Host "  kisayolunu kullanabilirsiniz." -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "NOT: Program yonetici haklariyla calistirilmaktadir." -ForegroundColor Cyan
Write-Host "     UAC istegi geldiyinde 'Evet' deyin." -ForegroundColor Cyan
Write-Host ""
Read-Host "Devam etmek icin Enter'a basin"
