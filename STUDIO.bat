@echo off
rem ClipMaker studio launcher. ASCII only on purpose: cmd.exe reads .bat in the OEM
rem codepage, and Cyrillic inside the file breaks command parsing (R22).
rem All human-facing text is printed by Python, which speaks UTF-8 after chcp.
chcp 65001 >nul
title ClipMaker Studio
cd /d "%~dp0"

set "PY=C:\Python314\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" "%~dp0scripts\clip_open.py" %*
set "CODE=%ERRORLEVEL%"

if not "%CODE%"=="0" (
  echo.
  echo   exit code %CODE% - see the error above
  echo.
  pause
)
