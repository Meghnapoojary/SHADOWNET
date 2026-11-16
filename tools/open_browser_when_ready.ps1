$base = "http://127.0.0.1:8000"
for ($attempt = 0; $attempt -lt 90; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri "$base/api/health" -TimeoutSec 2
        if ($health.status -eq "ok" -and $health.service -eq "SHADOWNET") {
            Start-Process $base
            exit 0
        }
    } catch { }
    Start-Sleep -Seconds 1
}
