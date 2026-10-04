# Screenshot the desktop without a mouse.
#
# The `?open=` deep link exists so a particular set of windows can be reviewed
# without clicking through to them, which is what makes this possible. Waits on
# `Sheetsworks.ready` indirectly via the virtual-time budget.
#
#   .\tools\shot.ps1 -Port 8311 -Name editor -Open editor
param(
  [int]$Port = 8300,
  [string]$Name = "shot",
  [string]$Open = "editor",
  [int]$Width = 1300,
  [int]$Height = 860
)

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
if (-not (Test-Path $chrome)) { throw "no chrome at $chrome" }

$out = Join-Path $root "out\$Name.png"
$url = "http://127.0.0.1:$Port/?open=$Open"

& $chrome --headless=new --disable-gpu --hide-scrollbars `
  --virtual-time-budget=18000 --window-size=$Width,$Height `
  --screenshot="$out" $url 2>&1 | Out-Null

if (-not (Test-Path $out)) { throw "no screenshot produced for $url" }
"{0}  {1:N0} bytes  {2}" -f $Name, (Get-Item $out).Length, $url
