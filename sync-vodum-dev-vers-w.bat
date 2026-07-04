@echo off
title Synchronisation VODUM-dev vers W:\vodum

set "SRC=C:\Users\sylva\OneDrive\Documents\Dev\VODUM-dev"
set "DST=W:\vodum"

echo.
echo ============================================
echo   Synchronisation VODUM-dev vers W:\vodum
echo ============================================
echo.

robocopy "%SRC%" "%DST%" /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 ^
 /XD ".git" "__pycache__" ".pytest_cache" ".mypy_cache" ".ruff_cache" ".pnpm-store" "node_modules" ^
 /XF "*.pyc" "*.pyo" "Thumbs.db" ".DS_Store"

echo.
if %ERRORLEVEL% LSS 8 (
    echo Synchronisation terminee avec succes.
) else (
    echo Une erreur est survenue. Code Robocopy : %ERRORLEVEL%
)

pause