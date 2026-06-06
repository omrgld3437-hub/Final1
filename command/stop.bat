@echo off
REM Root stop.bat cagirir (Manager, Web, Engine, Omeraltinhtml hepsi durur).
cd /d "%~dp0.."
call "%~dp0..\stop.bat" %*
