param(
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

$server = "llai@172.16.0.103"
$localPort = 8808
$remotePort = 8808
$studioUrl = "http://127.0.0.1:$localPort"
$waitScript = Join-Path $PSScriptRoot "wait-and-open.ps1"

if ($ValidateOnly) {
    if (-not (Test-Path -LiteralPath $waitScript -PathType Leaf)) {
        throw "找不到瀏覽器等待腳本：$waitScript"
    }
    Write-Host "啟動器設定檢查成功：$server / $studioUrl"
    exit 0
}

if (-not (Get-Command ssh.exe -ErrorAction SilentlyContinue)) {
    Write-Host "[錯誤] 找不到 Windows OpenSSH Client。" -ForegroundColor Red
    Write-Host "請從 Windows『選用功能』安裝 OpenSSH Client。"
    exit 1
}

$portInUse = $false
$client = [System.Net.Sockets.TcpClient]::new()
try {
    $connection = $client.ConnectAsync("127.0.0.1", $localPort)
    $portInUse = $connection.Wait(300) -and $client.Connected
}
catch {
    $portInUse = $false
}
finally {
    $client.Dispose()
}

if ($portInUse) {
    Write-Host "[錯誤] 本機連接埠 $localPort 已被使用。" -ForegroundColor Red
    Write-Host "請關閉先前的 SSH tunnel，或直接開啟 $studioUrl。"
    exit 2
}

Write-Host "==================================================" -ForegroundColor DarkGray
Write-Host "  VoxCPM2 Studio 自動啟動" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor DarkGray
Write-Host ""
Write-Host "伺服器：$server"
Write-Host "網址：  $studioUrl"
Write-Host ""
Write-Host "請輸入伺服器密碼。啟動後請保持此視窗開啟。"
Write-Host "按 Ctrl+C 可以停止服務及 SSH tunnel。"
Write-Host ""

$waitArguments = @(
    "-NoProfile"
    "-ExecutionPolicy", "Bypass"
    "-File", "`"$waitScript`""
    "-Url", "`"$studioUrl`""
    "-Port", $localPort
) -join " "

# This background helper is hidden; it opens the visible browser only when the
# SSH tunnel and web server are accepting connections.
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList $waitArguments | Out-Null

$forward = "${localPort}:127.0.0.1:${remotePort}"
$remoteCommand = "cd ~/voxcpm2-studio && git pull --ff-only && bash scripts/start-server.sh"
$sshArguments = @(
    "-o", "ExitOnForwardFailure=yes"
    "-o", "ServerAliveInterval=30"
    "-t"
    "-L", $forward
    $server
    $remoteCommand
)

& ssh.exe @sshArguments
$sshExit = $LASTEXITCODE

if ($sshExit -ne 0) {
    Write-Host ""
    Write-Host "[錯誤] VoxCPM2 或 SSH 連線已中止，錯誤碼：$sshExit" -ForegroundColor Red
}
else {
    Write-Host ""
    Write-Host "VoxCPM2 Studio 已停止。"
}

exit $sshExit
