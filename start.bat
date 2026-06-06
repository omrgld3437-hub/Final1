@echo off
setlocal EnableDelayedExpansion
set "ROOT=%~dp0"
cd /d "%ROOT%"
if not exist logs mkdir logs
if not exist .run mkdir .run

REM Git: sunucudaki yerel degisiklikleri atip guncel commit cek (stop.bat dahil, pull abort onleme)
if exist "%ROOT%.git" (
  echo [Git] Guncel commit cekiliyor...
  set "GIT_TERMINAL_PROMPT=0"
  git checkout -- start.bat restart.bat stop.bat 2>nul
  git pull
  if exist "%ROOT%.gitmodules" (
    echo [Git] Submodule guncelleniyor...
    git submodule update --init --recursive
  )
  for /f "delims=" %%h in ('git rev-parse --short HEAD 2^>nul') do echo [Git] Guncel commit: %%h
  echo.
)

REM urllib3/LibreSSL uyarisini bastir
if not defined PYTHONWARNINGS set "PYTHONWARNINGS=ignore:::urllib3"
if defined PYTHONWARNINGS set "PYTHONWARNINGS=%PYTHONWARNINGS%,ignore:::urllib3"

set "PY=python"
if exist "%ROOT%.venv\Scripts\python.exe" set "PY=%ROOT%.venv\Scripts\python.exe"

REM Ilk calistirma: .venv veya requirements yoksa Kurulum.bat otomatik calistir
if "%PY%"=="python" (
  echo.
  echo [Ilk calistirma] .venv bulunamadi. Kurulum.bat otomatik baslatiliyor...
  echo.
  if not exist "%ROOT%requirements.txt" (
    echo HATA: requirements.txt bulunamadi. Proje klasorunu kontrol edin.
    pause
    exit /b 1
  )
  call "%ROOT%Kurulum.bat" --icerde --otomatik
  if errorlevel 1 (
    echo.
    echo HATA: Kurulum basarisiz.
    pause
    exit /b 1
  )
  set "PY=%ROOT%.venv\Scripts\python.exe"
  if not exist "%ROOT%.venv\Scripts\python.exe" (
    echo.
    echo HATA: Kurulum tamamlanamadi. Kurulum.bat i elle baslatip tekrar deneyin.
    pause
    exit /b 1
  )
  echo.
  echo Kurulum tamamlandi. Servisler baslatiliyor...
  echo.
)

REM --- Manager (7999) ---
echo [1/4] Manager 7999 baslatiliyor...
set "MANAGER_PID=%ROOT%.run\manager.pid"
set "MANAGER_LOG=%ROOT%logs\manager.log"
if exist "%MANAGER_PID%" (
  set /p MP=<"%MANAGER_PID%"
  if defined MP tasklist /FI "PID eq !MP!" 2>nul | find /I "!MP!" >nul && goto :web
  del "%MANAGER_PID%" 2>nul
)
start /B "" "%PY%" -m manager_server >> "%MANAGER_LOG%" 2>&1
timeout /t 2 /nobreak >nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7999" ^| findstr "LISTENING"') do set "MP=%%a" & goto :mp
:mp
if defined MP echo %MP%> "%MANAGER_PID%"

:web
REM --- Web (8000) ---
echo [2/4] Web 8000 baslatiliyor...
set "WEB_PID=%ROOT%.run\web.pid"
set "WEB_LOG=%ROOT%logs\web.log"
if exist "%WEB_PID%" (
  set /p WP=<"%WEB_PID%"
  if defined WP tasklist /FI "PID eq !WP!" 2>nul | find /I "!WP!" >nul && goto :engine
  del "%WEB_PID%" 2>nul
)
REM Internetten erisim icin (Cloudflare/tunnel): set WEB_HOST=0.0.0.0
if not defined WEB_HOST set "WEB_HOST=127.0.0.1"
REM Windows'ta uvloop yok; --loop/--http atlanir (asyncio kullanilir)
start /B "" "%PY%" -m uvicorn app.main:app --host %WEB_HOST% --port 8000 --workers 2 --log-level info >> "%WEB_LOG%" 2>&1
timeout /t 2 /nobreak >nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do set "WP=%%a" & goto :wp
:wp
if defined WP echo %WP%> "%WEB_PID%"

:engine
REM --- Bot Engine (worker) ---
echo [3/4] Bot Engine worker baslatiliyor...
set "ENGINE_PID=%ROOT%.run\worker.pid"
set "ENGINE_LOG=%ROOT%logs\worker.log"
if exist "%ENGINE_PID%" (
  set /p EP=<"%ENGINE_PID%"
  if defined EP tasklist /FI "PID eq !EP!" 2>nul | find /I "!EP!" >nul && goto :end
  del "%ENGINE_PID%" 2>nul
)
start /B "" "%PY%" -m app.botengine.worker_main >> "%ENGINE_LOG%" 2>&1
timeout /t 2 /nobreak >nul
for /f "skip=1 tokens=1" %%a in ('wmic process where "CommandLine like '%%worker_main%%'" get ProcessId 2^>nul') do set "EP=%%a" & goto :ep
:ep
if defined EP echo %EP%> "%ENGINE_PID%"

REM --- Omeraltinhtml 8080 ---
echo [4/4] Omeraltinhtml 8080 baslatiliyor...
set "HTML_PID=%ROOT%.run\html.pid"
set "HTML_DIR="
if exist "%ROOT%Omeraltinhtml\start.py" set "HTML_DIR=%ROOT%Omeraltinhtml"
if not defined HTML_DIR if exist "%ROOT%Omeraltinhtml\calistir.bat" set "HTML_DIR=%ROOT%Omeraltinhtml"
if not defined HTML_DIR if exist "%ROOT%omeraltinhtml\start.py" set "HTML_DIR=%ROOT%omeraltinhtml"
if not defined HTML_DIR if exist "%ROOT%omeraltinhtml\calistir.bat" set "HTML_DIR=%ROOT%omeraltinhtml"
if not defined HTML_DIR for /d %%D in ("%ROOT%*") do if not defined HTML_DIR (
  set "dname=%%~nxD"
  echo !dname! | findstr /i "omeraltin" >nul && if exist "%%D\start.py" set "HTML_DIR=%%~fD"
  if not defined HTML_DIR echo !dname! | findstr /i "omeraltin" >nul && if exist "%%D\calistir.bat" set "HTML_DIR=%%~fD"
)
set "STARTPY=!HTML_DIR!\start.py"
set "CALISTIR=!HTML_DIR!\calistir.bat"
if exist "!STARTPY!" (
  call :start_html_py
) else if exist "!CALISTIR!" (
  call :do_start_calistir
) else (
  echo      Omeraltinhtml klasoru veya start.py bulunamadi, atlaniyor.
  echo      Sunucuda: git pull ve git submodule update --init --recursive
  echo      veya Omeraltinhtml klasorunu kopyalayin.
)

:end
echo.
echo ========================================
echo   Tum servisler baslatildi.
echo ========================================
echo   Manager : http://127.0.0.1:7999/ui
echo   Web     : http://127.0.0.1:8000
echo   HTML    : http://127.0.0.1:8080  - Omeraltinhtml
echo Acilmiyorsa: stop.bat ile durdurup 3 sn bekleyin, sonra start.bat tekrar baslatin.
echo "Dosya baska bir islem tarafindan kullaniliyor" hatasi: once stop.bat calistirin, 3 sn bekleyin, sonra start.bat.
echo.
REM Gorunum teshisi: diskteki dashboard surumu + build-info URL
set "DASHVER="
if exist "%ROOT%ui\dashboard.html" for /f "tokens=2 delims=:" %%a in ('findstr "VERSION:" "%ROOT%ui\dashboard.html" 2^>nul') do set "DASHVER=%%a"
if defined DASHVER set "DASHVER=%DASHVER: =%"
if defined DASHVER (echo   Dashboard ^(diskte^): !DASHVER!) else (echo   Dashboard ^(diskte^): okunamadi)
echo   Teshis URL ^(sunucunun okudugu surum^): http://127.0.0.1:8000/api/debug/build-info
echo   Eski gorunum = Tarayicida Ctrl+Shift+R; hala eskise build-info'daki dashboard_html_version ile yukaridaki surumu karsilastirin.
echo.
pause
endlocal
goto :eof

:start_html_py
start /B "" "!PY!" -u "!STARTPY!" >> "%ROOT%logs\html.log" 2>&1
timeout /t 1 /nobreak >nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080 " ^| findstr "LISTENING"') do echo %%a> "!HTML_PID!" & goto :eof
goto :eof

:do_start_calistir
pushd "!HTML_DIR!"
if not errorlevel 1 (
  start /B "" cmd /c "calistir.bat"
  timeout /t 1 /nobreak >nul
  popd
) else (
  popd
)
exit /b 0
