# Restarts the server ONLY if currently running (caps slow memory growth from the
# experimental prefix cache). Register: REGISTER-MAINTENANCE.bat. Runs daily 5am.
try { $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 5 -UseBasicParsing } catch { exit 0 }
if ($r.StatusCode -ne 200) { exit 0 }
wsl.exe -d Ubuntu-26.04 -u root --cd $PSScriptRoot -- bash killall-vllm.sh
Start-Process -FilePath "wsl.exe" -ArgumentList "-d","Ubuntu-26.04","-u","root","--cd",$PSScriptRoot,"--","bash","serve-wsl.sh" -WindowStyle Hidden
