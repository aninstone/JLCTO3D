@echo off
chcp 65001 >nul
setlocal
set "PS1=%~dp0JLCTO3D.ps1"
if not exist "%PS1%" (
    powershell.exe -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('JLCTO3D.ps1 not found','JLCTO3D Error')"
    goto :eof
)
:: Backup entry point: same behavior as .bat
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%PS1%" -FromBat -DroppedFile "%~1"
