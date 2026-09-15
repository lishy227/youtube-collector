@echo off
REM ---------------------------------------------------------------
REM open-browser.bat - launch Edge through the SAME exit as the collector
REM
REM Why: browser and terminal must share ONE session (same egress IP +
REM same cookies) so that any human-verification you pass in the browser
REM also covers the automated downloads.
REM
REM Do NOT enable system-wide / global / TUN mode in the proxy client-
REM it would capture traffic of EVERY process on this machine, including
REM services that depend on domestic-only API endpoints, and make their
REM requests hang silently (no error, just stuck).
REM ---------------------------------------------------------------
setlocal

set "PROXY=socks5://127.0.0.1:1234"
set "PROFILE=%~dp0.edge-profile"

set "EDGE=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" set "EDGE=C:\Program Files\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" (
  echo [ERROR] msedge.exe not found. Edit this file and set EDGE manually.
  pause
  exit /b 1
)

echo Launching Edge
echo   proxy   : %PROXY%
echo   profile : %PROFILE%
echo.
echo If YouTube shows a captcha / "sign in to confirm", solve it in this
echo window. The session stays in this profile and can be reused by:
echo   python collect.py "topic" -n 5 --cookies-from edge:%PROFILE%
echo.

start "" "%EDGE%" --proxy-server="%PROXY%" --user-data-dir="%PROFILE%" --no-first-run --no-default-browser-check https://www.youtube.com/

endlocal
