# Sizes WSL memory safely: enough for serving, never enough to starve Windows.
$cfg = "$env:USERPROFILE\.wslconfig"
if (Test-Path $cfg) { Write-Host ".wslconfig exists - leaving it alone"; exit 0 }
$ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB)
$cap = [math]::Min(16, [math]::Max(8, [int]($ram/2)))
@"
[wsl2]
memory=${cap}GB
swap=24GB

[experimental]
autoMemoryReclaim=gradual
"@ | Set-Content -Path $cfg -Encoding ASCII
Write-Host "Wrote .wslconfig (memory=${cap}GB swap=24GB). Restarting WSL..."
wsl --shutdown
