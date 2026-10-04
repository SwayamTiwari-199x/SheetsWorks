# Run the browser verification harness against a live server.
#
# The harness lives in tools/ rather than app/static/ on purpose. It PUTs to
# /profile, so anything that can reach it can overwrite the stored resume.
# Shipping it on the same origin as the app would put a destructive dev tool in
# production, so it is copied in for the run and removed again afterwards.
#
# Usage:  .\tools\run-ui-verify.ps1 <port>

# No $ErrorActionPreference = "Stop": Chrome writes harmless extension-registry
# warnings to stderr, and treating those as terminating errors stops the run
# before it starts.
$port = if ($args.Count -ge 1) { $args[0] } else { "8203" }

& "$PSScriptRoot\free-ports.ps1"
if ($LASTEXITCODE -ne 0) { Write-Output "ABORT: stale server"; exit 1 }

$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
if (-not (Test-Path $chrome)) {
    Write-Output "ABORT: no Chrome at $chrome"
    exit 1
}

# Keep the harness out of the served tree.
Remove-Item resume.db* -Force -ErrorAction SilentlyContinue
Copy-Item tools\_verify.html app\static\_verify.html -Force
Copy-Item tools\_verify.js   app\static\_verify.js   -Force
Copy-Item tools\_probe.js    app\static\_probe.js    -Force

$proc = $null
try {
    $proc = Start-Process -FilePath ".\.venv\Scripts\python.exe" `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", $port `
        -PassThru -RedirectStandardOutput "logs\ui.out" -RedirectStandardError "logs\ui.err" -NoNewWindow

    Start-Sleep -Seconds 11
    $health = (Invoke-WebRequest "http://127.0.0.1:$port/health" -UseBasicParsing).Content
    Write-Output "server pid $($proc.Id) -> $health"

    & $chrome --headless=new --disable-gpu --virtual-time-budget=45000 `
        --window-size=1400,900 --dump-dom "http://127.0.0.1:$port/static/_verify.html" 2>&1 |
        Out-File -Encoding utf8 out\ui_dom.txt
    Start-Sleep -Seconds 1

    $t = Get-Content out\ui_dom.txt -Raw
    if ($t -match '(?s)<pre id="verifyLog"[^>]*>(.*?)</pre>') {
        $log = $Matches[1] -replace '&quot;', '"' -replace '&amp;', '&' `
                           -replace '&lt;', '<' -replace '&gt;', '>'
        Write-Output $log
        if ($log -match '(\d+) failed') {
            exit ([int]$Matches[1] -gt 0)
        }
        exit 0
    }
    Write-Output "ABORT: the harness produced no log at all"
    exit 1
}
finally {
    if ($proc) { cmd /c "taskkill /T /F /PID $($proc.Id)" 2>&1 | Out-Null }
    Remove-Item app\static\_verify.html, app\static\_verify.js, app\static\_probe.js -Force -ErrorAction SilentlyContinue
}