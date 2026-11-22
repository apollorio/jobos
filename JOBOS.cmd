@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\start-dashboard.ps1"
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
  echo.
  echo JOBOS nao abriu. Codigo %CODE% devolvido por start-dashboard.ps1.
  echo Nenhum processo foi encerrado por este atalho.
  pause
)
exit /b %CODE%
