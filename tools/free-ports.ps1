# Kill anything left listening in the scratch port range before testing.
#
# This exists because it already happened: a uvicorn left over from an earlier
# run kept port 8200, so a verification script "failed" against code that had
# already been fixed. A test that silently talks to the wrong build is worse
# than no test, because it reports a defect that does not exist.
$range = 8180..8210
$listeners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $range -contains $_.LocalPort }

if ($listeners) {
    Write-Output "killing stale listeners:"
    foreach ($l in $listeners) {
        Write-Output ("  port {0} pid {1}" -f $l.LocalPort, $l.OwningProcess)
        cmd /c "taskkill /T /F /PID $($l.OwningProcess)" 2>&1 | Out-Null
    }
    Start-Sleep -Seconds 2
}

$still = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $range -contains $_.LocalPort }
if ($still) {
    Write-Output "ERROR: ports still held, refusing to test against a stale server"
    exit 1
}
Write-Output "port range clear"
exit 0