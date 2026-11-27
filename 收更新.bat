@echo off
REM ============================================================
REM  Developer only: receive the update Claude prepared.
REM  1. downloads the "pending" branch from GitHub
REM  2. checks the cloud tests (real Windows + Mac) passed
REM  3. applies it, opens the program window and measures smoothness
REM  4. publishes to GitHub -> co-workers get the update automatically
REM  If any step fails, nothing is published and the folder is restored.
REM ============================================================
if not exist "%~dp0magic\__main__.py" goto notool
call "%~dp0run_magic.bat" receive
exit /b

:notool
echo  [ERROR] Put this file inside the tool folder (next to run_magic.bat).
pause
exit /b 1
