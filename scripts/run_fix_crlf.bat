@echo off
cd /d "%~dp0"
call "%~dp0maintenance/run_fix_crlf.bat" %*
