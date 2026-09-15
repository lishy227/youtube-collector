@echo off
REM collect.bat - launcher that forces UTF-8 console (avoids garbled Chinese output)
chcp 65001 >nul
python "%~dp0collect.py" %*
