@echo off
REM Projeyi gunceller (start.bat dahil). Sadece sunucuda .git varsa calisir.
set "ROOT=%~dp0"
cd /d "%ROOT%"
echo Proje guncelleniyor...
if not exist "%ROOT%.git" (
  echo.
  echo .git yok - bu sunucu deploy ile kopyalandi.
  echo.
  echo Guncelleme: Mac/Linux veya Git Bash ile gelistirme PC nizde:
  echo   git pull
  echo   ./deploy/deploy.sh kullanici@sunucu:/proje/yolu
  echo Sonra bu sunucuda start.bat calistirin.
  echo.
  pause
  exit /b 1
)
set "GIT_TERMINAL_PROMPT=0"
git checkout -- start.bat restart.bat 2>nul
git pull
if exist "%ROOT%.gitmodules" git submodule update --init --recursive 2>nul
for /f "delims=" %%h in ('git rev-parse --short HEAD 2^>nul') do echo Guncel commit: %%h
echo.
echo Tamam. Simdi start.bat calistirin.
pause
