@echo off
REM ============================================================
REM  Finds a working Python that has numpy, scipy, pandas, matplotlib, tkinter.
REM  Called by run_magic.bat (same logic as in LowTemp launcher). Sets PYEXE, PYW, PYDIR.
REM  Exit code 0 = OK, 1 = not found (a message is shown first).
REM  Keep this file ASCII-only.
REM ============================================================
set "MT_DATA=%LOCALAPPDATA%\MagicTool"
if not exist "%MT_DATA%" mkdir "%MT_DATA%" >nul 2>&1
set "MT_LOG=%MT_DATA%\launcher.log"
set "PYEXE="
set "BAREPY="
echo [%date% %time%] searching for python > "%MT_LOG%"

REM ---- 1) the Python that worked last time (fast check) ----
set "REMEMBERED="
if exist "%MT_DATA%\python_path.txt" set /p REMEMBERED=<"%MT_DATA%\python_path.txt"
if defined REMEMBERED call :quick "%REMEMBERED%"
if defined PYEXE goto found

REM ---- 2) an active / registered conda ----
if defined CONDA_PREFIX call :try "%CONDA_PREFIX%\python.exe"
if defined PYEXE goto found
if defined CONDA_EXE for %%C in ("%CONDA_EXE%") do call :try "%%~dpC..\python.exe"
if defined PYEXE goto found

REM ---- 3) common install folders ----
for %%D in ("%USERPROFILE%\anaconda3" "%USERPROFILE%\miniconda3" "%USERPROFILE%\miniforge3" "%USERPROFILE%\mambaforge" "%LOCALAPPDATA%\anaconda3" "%LOCALAPPDATA%\miniconda3" "%ProgramData%\anaconda3" "%ProgramData%\miniconda3" "%ProgramData%\miniforge3" "C:\anaconda3" "C:\miniconda3" "C:\ProgramData\Anaconda3" "D:\anaconda3" "D:\miniconda3" "E:\anaconda3") do (
    if not defined PYEXE call :try "%%~D\python.exe"
)
if defined PYEXE goto found
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*" "C:\Program Files\Python3*") do (
    if not defined PYEXE call :try "%%~D\python.exe"
)
if defined PYEXE goto found

REM ---- 4) Windows registry (PEP 514; Anaconda and python.org register here) ----
for %%K in (HKCU HKLM) do (
    for /f "tokens=2,*" %%A in ('reg query "%%K\Software\Python" /s /v ExecutablePath 2^>nul ^| find "REG_SZ"') do (
        if not defined PYEXE call :try "%%B"
    )
)
if defined PYEXE goto found
for %%K in (HKCU HKLM) do (
    for /f "tokens=2,*" %%A in ('reg query "%%K\Software\Python" /s /ve 2^>nul ^| find "REG_SZ"') do (
        if not defined PYEXE call :try "%%B\python.exe"
    )
)
if defined PYEXE goto found

REM ---- 5) the py launcher, 6) PATH (skips the Microsoft Store alias) ----
for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do (
    if not defined PYEXE call :try "%%P"
)
if defined PYEXE goto found
for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PYEXE call :try "%%P"
)
if defined PYEXE goto found

if defined BAREPY goto offerpip
goto nopython

REM ============================================================
:found
for %%P in ("%PYEXE%") do set "PYDIR=%%~dpP"
set "PATH=%PYDIR%;%PYDIR%Library\mingw-w64\bin;%PYDIR%Library\usr\bin;%PYDIR%Library\bin;%PYDIR%Scripts;%PATH%"
set "PYW=%PYEXE%"
if exist "%PYDIR%pythonw.exe" set "PYW=%PYDIR%pythonw.exe"
echo found: %PYEXE%>> "%MT_LOG%"
exit /b 0

:offerpip
echo.
echo  Python was found, but it is missing required packages:
echo    %BAREPY%
echo  Required: numpy, scipy, pandas, matplotlib (and tkinter, included with Python).
echo.
choice /c YN /m " Install numpy / scipy / pandas / matplotlib now with pip"
if errorlevel 2 goto failed
"%BAREPY%" -m pip install --user --upgrade numpy scipy pandas matplotlib openpyxl
set "CAND=%BAREPY%"
set "BAREPY="
call :try "%CAND%"
if defined PYEXE goto found
echo.
echo  Still not working. If the log mentions tkinter, reinstall Python from
echo  python.org and keep the option "tcl/tk and IDLE" checked.
goto failed

:nopython
echo.
echo  ============================================================
echo   No usable Python was found on this computer.
echo  ============================================================
echo   Option A: install Anaconda (recommended), then run this again:
echo             https://www.anaconda.com/download
where winget >nul 2>nul
if errorlevel 1 goto failed
echo   Option B: install Python 3.12 automatically now (1-3 minutes).
echo.
choice /c YN /m " Install Python 3.12 now with winget"
if errorlevel 2 goto failed
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if not defined PYEXE call :try "%%~D\python.exe"
)
if defined PYEXE goto found
if defined BAREPY goto offerpip
goto failed

:failed
echo.
echo  Search details were written to:
echo    %MT_LOG%
echo.
pause
exit /b 1

REM ============================================================
REM  :quick  path  - accept if it runs at all (it worked before)
REM  :try    path  - accept only if numpy/scipy/pandas/matplotlib/tkinter import;
REM                  otherwise remember it in BAREPY as a pip candidate
REM ============================================================
:quick
if not exist "%~1" exit /b 1
"%~1" -c "import sys" >nul 2>&1
if errorlevel 1 exit /b 1
set "PYEXE=%~1"
exit /b 0

:try
setlocal
set "C=%~1"
if not exist "%C%" (
    endlocal
    exit /b 1
)
echo %C%| find /i "WindowsApps" >nul && (
    endlocal
    exit /b 1
)
set "D=%~dp1"
set "PATH=%D%;%D%Library\mingw-w64\bin;%D%Library\usr\bin;%D%Library\bin;%D%Scripts;%PATH%"
echo try: %C%>> "%MT_LOG%"
"%C%" -c "import numpy, scipy, pandas, matplotlib, tkinter" >> "%MT_LOG%" 2>&1
if errorlevel 1 goto try_bare
endlocal & set "PYEXE=%~1"
exit /b 0
:try_bare
"%C%" -c "import sys" >nul 2>&1
if errorlevel 1 (
    endlocal
    exit /b 1
)
endlocal & if not defined BAREPY set "BAREPY=%~1"
exit /b 1
