@echo off
schtasks /Create /F /TN "Qwen38Maintenance" /TR "powershell -ExecutionPolicy Bypass -File %~dp0maintenance.ps1" /SC DAILY /ST 05:00
echo Registered daily 5am only-if-running restart. Remove: schtasks /Delete /TN Qwen38Maintenance
pause
