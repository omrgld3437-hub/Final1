REM Windows batch: restart.
@echo off
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"
REM Git: yerel degisiklikleri atip guncel commit cek
if exist "%ROOT%.git" (
  echo [Git] Guncel commit cekiliyor...
  set "GIT_TERMINAL_PROMPT=0"
  git checkout -- start.bat restart.bat 2>nul
  git pull
  if exist "%ROOT%.gitmodules" (
    echo [Git] Submodule guncelleniyor...
    git submodule update --init --recursive
  )
  for /f "delims=" %%h in ('git rev-parse --short HEAD 2^>nul') do echo [Git] Guncel commit: %%h
  echo.
)
echo Restart: once stop.bat, sonra start.bat...
echo.
call "%ROOT%\ops\stop.bat"
echo.
echo Simdi start.bat calistiriliyor...
echo.
call "%ROOT%\ops\start.bat"
echo.
echo Restart tamamlandi.
pause
endlocal
