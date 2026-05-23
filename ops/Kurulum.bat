REM Windows batch: Kurulum.
@echo off
REM Cift tiklayinca pencere hemen kapanmasin: kendini cmd /k ile ac
if not "%~1"=="--icerde" (
  cmd /k "%~f0" --icerde
  exit /b
)
title TraderTrailing - Kurulum
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0.."
set "ROOT=%~dp0.."
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

echo.
echo ========================================
echo   TraderTrailing - Windows Kurulum
echo ========================================
echo Klasor: %ROOT%
echo.

REM Python 3.12 veya 3.13 ara (3.14 uyumlu degil)
set "PYEXE="
for %%V in (3.12 3.13) do (
  if not defined PYEXE (
    py -%%V -c "print('ok')" >nul 2>&1 && set "PYEXE=py -%%V"
  )
)

if not defined PYEXE (
  echo HATA: Python 3.12 veya 3.13 bulunamadi.
  echo.
  echo Yapmaniz gerekenler:
  echo 1. https://www.python.org/downloads/ adresinden Python 3.12 indirin
  echo 2. Kurarken "Add python.exe to PATH" isaretleyin
  echo 3. CMD acip "cd %ROOT%" yazin, sonra "Kurulum.bat" yazin
  echo.
  set "KURULUM_HATA=1"
  goto son
)

echo Python bulundu: %PYEXE%
echo.

REM Eski .venv varsa once portlari kapat, sonra sil
if exist "%ROOT%\.venv" (
  echo Eski .venv var; once sunucular kapatiliyor - port 7999, 8000...
  for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":7999" ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
  for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
  timeout /t 2 /nobreak >nul
  echo .venv siliniyor...
  rmdir /s /q "%ROOT%\.venv" 2>nul
  if exist "%ROOT%\.venv" (
    echo Hala kilitli; Python surecleri kapatiliyor...
    taskkill /IM python.exe /F >nul 2>&1
    timeout /t 2 /nobreak >nul
    rmdir /s /q "%ROOT%\.venv" 2>nul
  )
  if exist "%ROOT%\.venv" (
    echo UYARI: .venv silinemedi. Bilgisayari yeniden baslatin, sonra Kurulum.bat tekrar calistirin.
    echo.
    set "KURULUM_HATA=1"
    goto son
  )
  echo .venv silindi.
  echo.
)

REM Yeni .venv olustur
echo Sanal ortam olusturuluyor...
%PYEXE% -m venv "%ROOT%\.venv"
if errorlevel 1 (
  echo HATA: venv olusturulamadi.
  set "KURULUM_HATA=1"
  goto son
)
echo .venv olusturuldu.
echo.

REM Paketleri yukle
echo Bagimliliklar yukleniyor (1-2 dakika surebilir)...
"%ROOT%\.venv\Scripts\pip.exe" install --upgrade pip
"%ROOT%\.venv\Scripts\pip.exe" install -r "%ROOT%\requirements.txt" --prefer-binary
if errorlevel 1 (
  echo.
  echo HATA: Paket kurulumu basarisiz.
  set "KURULUM_HATA=1"
  goto son
)

echo.
echo ========================================
echo   Kurulum tamamlandi.
echo ========================================
if "%~2"=="--otomatik" (
  echo start.bat kurulumdan sonra otomatik devam edecek.
) else (
  echo Simdi proje kokunden start.bat calistirin.
)
echo ========================================
echo.

:son
echo.
if not "%~2"=="--otomatik" (
  echo Pencereyi kapatmak icin bir tusa basin...
  pause >nul
)
if defined KURULUM_HATA exit /b 1
exit /b 0
