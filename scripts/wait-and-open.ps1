param(
    [string]$Url = "http://127.0.0.1:8808",
    [int]$Port = 8808,
    [int]$TimeoutSeconds = 300
)

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)

while ((Get-Date) -lt $deadline) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connection = $client.ConnectAsync("127.0.0.1", $Port)
        if ($connection.Wait(500) -and $client.Connected) {
            # The browser is intentionally visible: this helper exists to open
            # the user-facing interface only after the SSH tunnel is ready.
            Start-Process $Url
            exit 0
        }
    }
    catch {
        # The tunnel/server is not ready yet; retry until the deadline.
    }
    finally {
        $client.Dispose()
    }
    Start-Sleep -Milliseconds 750
}

exit 1
