@echo off
setlocal DisableDelayedExpansion
rem Use an absolute script path: Explorer may start CMD outside this directory.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-windows.ps1" %*
set "installExitCode=%ERRORLEVEL%"
echo.
if "%installExitCode%"=="0" (
    echo Installation completed.
) else (
    echo Installation failed. Exit code: %installExitCode%
    echo See the error message above.
)
echo.
pause
exit /b %installExitCode%
