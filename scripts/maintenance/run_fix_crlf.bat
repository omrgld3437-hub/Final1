REM Windows batch: run fix crlf.
@echo off
REM Windows: Tum .bat dosyalarini CRLF yapar (Mac'ten kopya sonrasi bozulma cozumu).
REM .ps1 dosyasi gerekmez; PowerShell komutu bat icinde.
cd /d "%~dp0.."
set "ROOT=%~dp0.."
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
powershell -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%ROOT%'; $count=0; Get-ChildItem -Path . -Filter '*.bat' -Recurse -File | ForEach-Object { $c=[System.IO.File]::ReadAllText($_.FullName); $c=$c -replace ([char]13+[char]10), ([char]10) -replace ([char]10), ([char]13+[char]10); [System.IO.File]::WriteAllText($_.FullName,$c); Write-Host ('CRLF: '+$_.FullName); $count++ }; Write-Host ''; Write-Host ('Tamamlandi: '+$count+' .bat dosyasi CRLF yapildi.')"
echo.
pause
