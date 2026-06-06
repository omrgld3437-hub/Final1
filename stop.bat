@echo off
setlocal EnableDelayedExpansion
echo [stop.bat] Baslatiliyor...
set "ROOT=%~dp0"
cd /d "%ROOT%"
if errorlevel 1 (
  echo HATA: Proje klasorune geçilemedi: %ROOT%
  pause
  exit /b 1
)

set "MANAGER_PID=%ROOT%.run\manager.pid"
set "WEB_PID=%ROOT%.run\web.pid"
set "ENGINE_PID=%ROOT%.run\worker.pid"
set "HTML_PID=%ROOT%.run\html.pid"

REM ========== 0) PORT-BASED KILL - sadece PID^>0 (PID 0 taskkill hatasi onlenir) ==========
echo [0/8] Portlari serbest birakiyor (80, 443, 7999, 8000, 8080)...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr "0.0.0.0:80 "') do if %%a gtr 0 taskkill /PID %%a /F /T 2>nul
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr "0.0.0.0:443 "') do if %%a gtr 0 taskkill /PID %%a /F /T 2>nul
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":7999 "') do if %%a gtr 0 taskkill /PID %%a /F /T 2>nul
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000 "') do if %%a gtr 0 taskkill /PID %%a /F /T 2>nul
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8080 "') do if %%a gtr 0 taskkill /PID %%a /F /T 2>nul
timeout /t 2 /nobreak >nul

REM ========== 1) NGINX - GRACEFUL THEN FORCE (CRITICAL - RELEASES STATIC ROOT) ==========
echo [1/8] Stopping Nginx...
where nginx >nul 2>&1
if errorlevel 1 (
  echo Nginx bulunamadi, atlaniyor.
) else (
  nginx -s quit 2>nul
  timeout /t 2 /nobreak >nul
  tasklist /FI "IMAGENAME eq nginx.exe" 2>nul | find /I "nginx.exe" >nul
  if errorlevel 1 (
    echo Nginx kapatildi.
  ) else (
    taskkill /IM nginx.exe /F /T 2>nul
    timeout /t 1 /nobreak >nul
    tasklist /FI "IMAGENAME eq nginx.exe" 2>nul | find /I "nginx.exe" >nul
    if not errorlevel 1 echo [UYARI] Nginx hala calisiyor olabilir. Yonetici olarak calistirin.
  )
)

REM ========== 2) BACKEND / MANAGER / WORKER - PID FILES THEN PROCESS ==========
echo [2/8] Stopping Manager, Web, Engine, Omeraltinhtml (PID files)...
if exist "%MANAGER_PID%" (
  set /p MP=<"%MANAGER_PID%" 2>nul
  if defined MP taskkill /PID !MP! /T /F 2>nul
  del "%MANAGER_PID%" 2>nul
)
if exist "%WEB_PID%" (
  set /p WP=<"%WEB_PID%" 2>nul
  if defined WP taskkill /PID !WP! /T /F 2>nul
  del "%WEB_PID%" 2>nul
)
if exist "%ENGINE_PID%" (
  set /p EP=<"%ENGINE_PID%" 2>nul
  if defined EP taskkill /PID !EP! /T /F 2>nul
  del "%ENGINE_PID%" 2>nul
)
if exist "%HTML_PID%" (
  set /p HP=<"%HTML_PID%" 2>nul
  if defined HP taskkill /PID !HP! /T /F 2>nul
  del "%HTML_PID%" 2>nul
)

REM ========== 3) REMAINING PROCESSES - WMIC (SKIP IF WMIC FAILS) ==========
echo [3/8] Stopping remaining Manager/Web/Worker/HTML processes...
where wmic >nul 2>&1
if not errorlevel 1 (
  for /f "skip=1 tokens=1" %%a in ('wmic process where "CommandLine like '%%manager_server%%'" get ProcessId 2^>nul') do taskkill /PID %%a /F /T 2>nul
  for /f "skip=1 tokens=1" %%a in ('wmic process where "CommandLine like '%%uvicorn%%app.main%%'" get ProcessId 2^>nul') do taskkill /PID %%a /F /T 2>nul
  for /f "skip=1 tokens=1" %%a in ('wmic process where "CommandLine like '%%worker_main%%'" get ProcessId 2^>nul') do taskkill /PID %%a /F /T 2>nul
  for /f "skip=1 tokens=1" %%a in ('wmic process where "CommandLine like '%%omeraltinhtml%%'" get ProcessId 2^>nul') do taskkill /PID %%a /F /T 2>nul
  for /f "skip=1 tokens=1" %%a in ('wmic process where "CommandLine like '%%start.py%%'" get ProcessId 2^>nul') do taskkill /PID %%a /F /T 2>nul
)

REM ========== 4) PORTS 7999 / 8000 / 8080 - FULL RELEASE ==========
echo [4/8] Releasing ports 80, 443, 7999, 8000, 8080 (PID^>0 only)...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr "0.0.0.0:80 "') do if %%a gtr 0 taskkill /PID %%a /F /T 2>nul
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr "0.0.0.0:443 "') do if %%a gtr 0 taskkill /PID %%a /F /T 2>nul
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":7999 "') do if %%a gtr 0 taskkill /PID %%a /F /T 2>nul
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000 "') do if %%a gtr 0 taskkill /PID %%a /F /T 2>nul
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8080 "') do if %%a gtr 0 taskkill /PID %%a /F /T 2>nul
timeout /t 2 /nobreak >nul

REM ========== 5) FILE LOCK CHECK (INFO ONLY) ==========
echo [5/8] Checking file locks...
set "LOCKDIR=%ROOT%Omeraltinhtml"
if exist "!LOCKDIR!" (
  echo. 2> "!LOCKDIR!\.lockcheck" 2>nul
  if errorlevel 1 (
    echo [UYARI] Omeraltinhtml klasoru kilitli olabilir. Explorer penceresini kapatip tekrar deneyin.
  ) else (
    del "!LOCKDIR!\.lockcheck" 2>nul
  )
)

REM ========== 6) FINAL VERIFICATION - PORT KILL AGAIN IF ANY REMAIN ==========
echo [6/8] Final verification - port kill again (PID^>0 only)...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr "0.0.0.0:80 "') do if %%a gtr 0 taskkill /PID %%a /F /T 2>nul
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr "0.0.0.0:443 "') do if %%a gtr 0 taskkill /PID %%a /F /T 2>nul
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":7999 "') do if %%a gtr 0 taskkill /PID %%a /F /T 2>nul
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000 "') do if %%a gtr 0 taskkill /PID %%a /F /T 2>nul
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8080 "') do if %%a gtr 0 taskkill /PID %%a /F /T 2>nul
timeout /t 2 /nobreak >nul

echo [7/8] Son port kontrolu...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000 "') do if %%a gtr 0 taskkill /PID %%a /F /T 2>nul
timeout /t 1 /nobreak >nul

echo [8/8] Port 80/443 (web) son kontrol...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr "0.0.0.0:80 "') do if %%a gtr 0 taskkill /PID %%a /F /T 2>nul
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr "0.0.0.0:443 "') do if %%a gtr 0 taskkill /PID %%a /F /T 2>nul
timeout /t 1 /nobreak >nul

echo.
echo ========================================
echo   All services stopped.
echo   Ports released (80, 443, 7999, 8000, 8080).
echo   No file locks remaining (Nginx/static root released).
echo ========================================
echo Eger tarayicidan hala erisim varsa: stop.bat'a sag tiklayip
echo "Yonetici olarak calistir" ile tekrar calistirin.
echo.
echo Port ve log dosyalarinin serbest kalmasi icin 3 saniye bekleniyor...
timeout /t 3 /nobreak >nul
endlocal
echo.
pause
