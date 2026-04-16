@echo off
chcp 65001 >nul
title Kanser TManager - Baslatma Menusu
color 0b

:MENU
cls
echo ========================================================
echo                  KANSER TMANAGER V4.0
echo                   Dev: Tarikdxd
echo ========================================================
echo.
echo [1] Uygulamayi Baslat
echo [2] Kutuphaneleri Kur (Ilk Kurulum Icin)
echo [3] Cikis
echo.
set /p secim="Lutfen bir islem secin (1-3): "

if "%secim%"=="1" goto BASLAT
if "%secim%"=="2" goto KURULUM
if "%secim%"=="3" goto CIKIS
goto MENU

:KURULUM
cls
color 0e
echo Kutuphaneler kuruluyor, lutfen bekleyin...
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
echo Kurulum Tamamlandi!
pause
color 0b
goto MENU

:BASLAT
cls
echo Kanser TManager baslatiliyor...
.\.venv\Scripts\python.exe ghost_joiner.py
pause
goto MENU

:CIKIS
exit
