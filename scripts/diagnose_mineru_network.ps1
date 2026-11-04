# MinerU network diagnostics for Windows PowerShell 5.1+
# Read-only: does not read .env, access API tokens, submit OCR, or change network settings.
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
$hostsToCheck = @("mineru.net", "cdn-mineru.openxlab.org.cn")
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = Join-Path $PSScriptRoot "mineru_network_diagnostic_$stamp.txt"
Start-Transcript -Path $logPath -Force | Out-Null

function Section([string]$name) {
    Write-Host ""
    Write-Host "========== $name ==========" -ForegroundColor Cyan
}
function Test-Tcp([string]$hostName) {
    Write-Host ""
    Write-Host "[TCP] $($hostName):443"
    try {
        $r = Test-NetConnection -ComputerName $hostName -Port 443 -WarningAction SilentlyContinue
        if ($r.TcpTestSucceeded) { Write-Host "PASS" -ForegroundColor Green }
        else { Write-Host "FAIL" -ForegroundColor Red }
        Write-Host "RemoteAddress=$($r.RemoteAddress); SourceAddress=$($r.SourceAddress)"
    } catch { Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red }
}
function Test-Tls([string]$hostName) {
    Write-Host ""
    Write-Host "[TLS 1.2] $hostName"
    $tcp = $null
    $ssl = $null
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.ReceiveTimeout = 10000
        $tcp.SendTimeout = 10000
        $tcp.Connect($hostName, 443)
        $ssl = New-Object System.Net.Security.SslStream($tcp.GetStream(), $false)
        $ssl.AuthenticateAsClient(
            $hostName, $null,
            [System.Security.Authentication.SslProtocols]::Tls12,
            $true
        )
        Write-Host "PASS: $($ssl.SslProtocol), cipher=$($ssl.CipherAlgorithm)" -ForegroundColor Green
    } catch {
        Write-Host "FAIL: $($_.Exception.GetType().FullName): $($_.Exception.Message)" -ForegroundColor Red
    } finally {
        if ($ssl) { $ssl.Dispose() }
        if ($tcp) { $tcp.Dispose() }
    }
}

try {
    Section "1. Environment"
    Write-Host "Time: $(Get-Date -Format o)"
    Write-Host "Computer: $env:COMPUTERNAME"
    Write-Host "PowerShell: $($PSVersionTable.PSVersion)"
    Write-Host "OS: $([Environment]::OSVersion.VersionString)"

    Section "2. Proxy configuration (credentials are not printed)"
    foreach ($name in @("HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","http_proxy","https_proxy","all_proxy")) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ([string]::IsNullOrWhiteSpace($value)) { Write-Host "$name = not set" }
        else {
            try {
                $u = [Uri]$value
                Write-Host "$name = $($u.Scheme)://$($u.Host):$($u.Port)"
            } catch { Write-Host "$name = set (value hidden)" }
        }
    }
    Write-Host ""
    Write-Host "WinHTTP proxy:"
    netsh winhttp show proxy
    Write-Host "Current-user Internet Settings:"
    try {
        $p = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        Write-Host "ProxyEnable=$($p.ProxyEnable); ProxyServer=$($p.ProxyServer); AutoConfigURL=$($p.AutoConfigURL)"
    } catch { Write-Host "Could not read current-user proxy settings." }

    Section "3. DNS"
    foreach ($h in $hostsToCheck) {
        Write-Host ""
        Write-Host "[DNS] $h"
        try {
            Resolve-DnsName $h -Type A -ErrorAction Stop |
                Select-Object Name, Type, IPAddress | Format-Table -AutoSize
        } catch { Write-Host "FAIL: $($_.Exception.Message)" -ForegroundColor Red }
    }

    Section "4. TCP port 443"
    foreach ($h in $hostsToCheck) { Test-Tcp $h }

    Section "5. TLS 1.2 with certificate validation"
    foreach ($h in $hostsToCheck) { Test-Tls $h }

    Section "6. HTTPS via curl.exe"
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        foreach ($h in $hostsToCheck) {
            Write-Host ""
            Write-Host "[curl] https://$h/"
            & curl.exe -I --connect-timeout 10 --max-time 20 --max-redirs 0 "https://$h/" 2>&1
            Write-Host "curl_exit_code=$LASTEXITCODE"
        }
    } else { Write-Host "curl.exe not found; skipped." }

    Section "7. Python httpx (proxy enabled vs disabled)"
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $code = @'
import httpx
for host in ("mineru.net", "cdn-mineru.openxlab.org.cn"):
    for trust_env in (True, False):
        print(f"\n[httpx] host={host}, trust_env={trust_env}")
        try:
            with httpx.Client(
                timeout=httpx.Timeout(15.0, connect=8.0),
                follow_redirects=False,
                trust_env=trust_env,
            ) as client:
                r = client.get(f"https://{host}/")
            print("HTTP", r.status_code, "server=", r.headers.get("server"))
            print("PASS: HTTPS request received an HTTP response")
        except Exception as exc:
            print("FAIL:", type(exc).__name__, str(exc))
'@
        $code | & python -
        Write-Host "python_exit_code=$LASTEXITCODE"
    } else { Write-Host "python.exe not found; skipped." }

    Section "8. Interpretation"
    Write-Host "HTTP 403/404/405 still proves DNS/TCP/TLS/HTTP reached a server."
    Write-Host "A root-path test does NOT prove a signed ZIP download will work."
    Write-Host "Compare CDN results with mineru.net; CDN is the failing host in this incident."
    Write-Host "No MinerU token or signed download URL is read, printed, or requested."
    Write-Host ""
    Write-Host "Log saved to: $logPath"
} finally {
    Stop-Transcript | Out-Null
}
Write-Host ""
Write-Host "Diagnostic finished. Send the TXT log back for analysis." -ForegroundColor Green
Read-Host "Press Enter to close"
