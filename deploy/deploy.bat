REM Windows batch: deploy.
@echo off
REM Deploy script (Windows) - Sadece DEGISKEN dosyalari sunucuya kopyalanir
REM SABIT dosyalar (.env, *.db, logs, vb.) atlanir
REM
REM Gereksinim: rsync Windows'ta kurulu olmali (Git Bash veya WSL ile)
REM Alternatif: WinSCP, FileZilla veya manuel kopyala-yapistir
REM
REM Kullanim: deploy.bat user@sunucu.com:/opt/final1/current

setlocal
set DEST=%1
if "%DEST%"=="" set DEST=%RSYNC_DEST%
if "%DEST%"=="" (
    echo Kullanim: %0 user@host:/path/to/project
    echo    veya:  set RSYNC_DEST=user@host:/path ^& %0
    exit /b 1
)

set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..
set EXCLUDE_FILE=%SCRIPT_DIR%SABIT_DOSYALAR.txt

where rsync >nul 2>&1
if errorlevel 1 (
    echo Hata: rsync bulunamadi. Git Bash veya WSL kullanin.
    echo Alternatif: SABIT_DOSYALAR.txt listesine bakarak manuel kopyalayin.
    exit /b 1
)

echo Deploy: %PROJECT_ROOT% -^> %DEST%
echo SABIT dosyalar atlaniyor...
echo

rsync -avz --delete --exclude-from="%EXCLUDE_FILE%" "%PROJECT_ROOT%/" "%DEST%/"

echo.
echo Deploy tamamlandi.
