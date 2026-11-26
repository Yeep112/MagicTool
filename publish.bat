@echo off
REM ============================================================
REM  Developer only: upload this folder to GitHub in one step.
REM  (git add + commit + push, version number from release.json;
REM   if you changed code yourself, it bumps the version for you.)
REM  Before uploading: clears notebook outputs, blocks data files,
REM  runs the self test. Co-workers then get the update automatically.
REM ============================================================
if not exist "%~dp0magic\__main__.py" goto notool
call "%~dp0run_magic.bat" publish
exit /b

:notool
echo  [ERROR] Put publish.bat inside the tool folder (next to run_magic.bat).
pause
exit /b 1
