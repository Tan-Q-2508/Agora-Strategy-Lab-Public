# Start Agora's tray from a tool (a Claude session) so it outlives that tool (D-218).
#
# A process started from a tool is a child of that tool's process tree, and a tool's clean-up ends
# the whole tree. The venv's pythonw.exe is a small launcher that ties its real Python to it (a
# kill-on-close Windows job), so the end of a launcher takes its Python with it at once, with no
# crash and no log line: that is how Agora vanished on 6 Nov. Win32_Process.Create starts Agora from
# the WMI service, which belongs to no tool's tree, as a double-click would.
# The user never needs this; double-clicking Start Agora is already outside any job.
param([string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path)

$py = Join-Path $Root ".venv\Scripts\pythonw.exe"
$line = "cmd /c set PYTHONUTF8=1&& start `"`" `"$py`" -m backend.desktop.tray"
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = $line; CurrentDirectory = $Root
}
if ($r.ReturnValue -ne 0) { Write-Error "Windows refused to start Agora ($($r.ReturnValue))"; exit 1 }
Write-Output "started"
