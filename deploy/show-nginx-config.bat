REM Windows batch: show-nginx-config.
@echo off
REM Sunucuda (Windows) Nginx yapisini gosterir. Ciktida mevcut nginx.conf ve include edilen dosyalar yer alir.
REM Calistir: deploy\show-nginx-config.bat  (proje kokunden) veya cift tikla.
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%.."

echo ========================================
echo  Nginx konum ve nginx.conf aranıyor...
echo ========================================
echo.

where nginx 2>nul
if errorlevel 1 (
  echo "nginx" PATH'ta bulunamadi. Asagidaki yollara bakiliyor:
) else (
  echo.
)

set "CONF="
for %%D in (
  "C:\nginx\conf\nginx.conf"
  "C:\Program Files\nginx\conf\nginx.conf"
  "C:\Program Files (x86)\nginx\conf\nginx.conf"
  "%ProgramFiles%\nginx\conf\nginx.conf"
) do (
  if exist %%D set "CONF=%%~D"
)
if not defined CONF (
  echo Hicbir standart yolda nginx.conf bulunamadi.
  echo Nginx kurulum dizininizi biliyorsaniz, oradaki conf\nginx.conf dosyasini acip icerigini kopyalayin.
  pause
  exit /b 1
)

echo Bulunan ana config: %CONF%
echo.
echo ========================================
echo  nginx.conf icerigi
echo ========================================
type "%CONF%"
echo.
for %%F in ("%CONF%") do set "CONFDIR=%%~dpF"
if exist "%CONFDIR%conf.d" (
  echo ========================================
  echo  conf.d icerigi
  echo ========================================
  for %%f in ("%CONFDIR%conf.d\*.conf") do (
    echo --- %%f ---
    type "%%f"
    echo.
  )
)
if exist "%CONFDIR%sites-enabled" (
  echo ========================================
  echo  sites-enabled icerigi
  echo ========================================
  for %%f in ("%CONFDIR%sites-enabled\*") do (
    echo --- %%f ---
    type "%%f"
    echo.
  )
)
echo ========================================
echo  Bitti. Yukaridaki ciktiyi kopyalayip paylasabilirsiniz.
echo ========================================
pause
