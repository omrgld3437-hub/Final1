@echo off
REM Root restart.bat cagirir (stop + start).
cd /d "%~dp0.."
call "%~dp0..\restart.bat" %*
