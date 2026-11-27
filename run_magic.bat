@echo off
REM ============================================================
REM  Magic Tool - opens the program.
REM  The console closes right away; the program keeps running.
REM  This file can be copied anywhere. Keep it ASCII-only.
REM
REM  run_magic.bat                 open the program
REM  run_magic.bat some.dat        open the program with that file or folder
REM  run_magic.bat install         Start menu + desktop shortcuts
REM  run_magic.bat selftest        run the self test (synthetic data only)
REM  run_magic.bat diag            show diagnostics
REM  run_magic.bat update          check GitHub for a new version
REM  run_magic.bat publish         developer: upload this version to GitHub
REM  run_magic.bat receive         developer: take the update Claude put on "pending", test, publish
REM ============================================================
setlocal EnableExtensions
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "MT_DATA=%LOCALAPPDATA%\MagicTool"

REM ---- tool folder: next to this file, otherwise the remembered one ----
set "TOOL="
if exist "%~dp0magic\__main__.py" set "TOOL=%~dp0"
if not defined TOOL if exist "%MT_DATA%\tool_path.txt" set /p TOOL=<"%MT_DATA%\tool_path.txt"
if defined TOOL if not exist "%TOOL%\magic\__main__.py" set "TOOL="
if not defined TOOL goto notool
cd /d "%TOOL%"
call "%TOOL%\magic_env.bat"
if errorlevel 1 exit /b 1

set "ARG=%~1"
if not defined ARG goto gui
if /i "%ARG%"=="gui" goto gui
if /i "%ARG%"=="selftest" goto selftest
if /i "%ARG%"=="install" goto install
if /i "%ARG%"=="uninstall" goto uninstall
if /i "%ARG%"=="update" goto update
if /i "%ARG%"=="diag" goto diag
if /i "%ARG%"=="publish" goto publish
if /i "%ARG%"=="receive" goto receive
goto guipath

:gui
start "" "%PYW%" -m magic app
exit /b

:guipath
start "" "%PYW%" -m magic app "%~1"
exit /b

:selftest
"%PYEXE%" -m magic selftest
pause
exit /b

:install
"%PYEXE%" -m magic install
pause
exit /b

:uninstall
"%PYEXE%" -m magic uninstall
pause
exit /b

:update
"%PYEXE%" -m magic update
pause
exit /b

:diag
"%PYEXE%" -m magic diag
pause
exit /b

:publish
"%PYEXE%" -m magic publish
pause
exit /b

:receive
"%PYEXE%" -m magic receive
pause
exit /b

:notool
echo.
echo  [ERROR] Cannot find the Magic Tool folder.
echo  Please unzip the whole folder first (do not run it from inside the .zip),
echo  then run this file once from inside that folder.
echo  After that, copies of this file work from any location.
echo.
pause
exit /b 1
