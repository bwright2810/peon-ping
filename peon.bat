@echo off
:: peon-ping: Windows batch wrapper for peon.py
:: Allows calling "peon --pause" instead of "python peon.py --pause"

:: Get the directory where this batch file is located
set "PEON_DIR=%~dp0"

:: Remove trailing backslash
set "PEON_DIR=%PEON_DIR:~0,-1%"

:: Call Python script with all arguments, passing stdin through
python "%PEON_DIR%\peon.py" %*
