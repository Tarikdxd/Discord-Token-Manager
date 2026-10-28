@echo off
chcp 65001 >nul
title Discord Token Manager - Başlatıcı
color 0b

:: Dizin kontrolü
cd /d "%~dp0"

:MENU
cls
echo ========================================================
echo               DISCORD TOKEN MANAGER V4.0
echo             Gelişmiş Çoklu Hesap ve Ses Yöneticisi
echo ========================================================
echo.
echo   [1] Uygulamayı Başlat (GUI)
echo   [2] Bağımlılıkları Kur / Güncelle (requirements.txt)
echo   [3] Ses Botu Modülünü Başlat (Hafif Sürüm)
echo   [4] Çıkış
echo.
echo ========================================================
set /p secim="İşlem seçiniz (1-4): "

if "%secim%"=="1" goto BASLAT
if "%secim%"=="2" goto KURULUM
if "%secim%"=="3" goto SES_BOTU
if "%secim%"=="4" goto CIKIS
goto MENU

:KURULUM
cls
color 0e
echo ========================================================
echo   Gerekli Python Kütüphaneleri Kuruluyor...
echo ========================================================
echo.

:: Python kontrolü
python --version >nul 2>&1
if errorlevel 1 (
    color 0c
    echo [HATA] Python sisteminizde kurulu değil veya PATH'e eklenmemiş!
    echo Lütfen https://www.python.org adresinden Python 3.10+ indirip kurun.
    pause
    goto MENU
)

:: Sanal ortam (.venv) kontrolü
if not exist ".venv" (
    echo [.venv] Sanal ortam oluşturuluyor...
    python -m venv .venv
)

echo Kütüphaneler güncelleniyor...
call .\.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo ========================================================
echo [OK] Kurulum başarıyla tamamlandı!
echo ========================================================
pause
color 0b
goto MENU

:BASLAT
cls
echo Discord Token Manager başlatılıyor...
if exist ".venv\Scripts\python.exe" (
    .\.venv\Scripts\python.exe ghost_joiner.py
) else (
    python ghost_joiner.py
)
if errorlevel 1 (
    echo.
    echo [UYARI] Bir hata oluştu. Lütfen önce [2] seçeneği ile kütüphaneleri kurduğunuzdan emin olun.
    pause
)
goto MENU

:SES_BOTU
cls
echo Ses Botu Modülü başlatılıyor...
if exist ".venv\Scripts\python.exe" (
    .\.venv\Scripts\python.exe ses_botu.py
) else (
    python ses_botu.py
)
pause
goto MENU

:CIKIS
exit /b 0
