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

    Section "6. HTTPS via curl.exe (direct and explicit local proxy)"
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        Write-Host "curl_path=$($curl.Source)"
        & curl.exe --version | Select-Object -First 1
        foreach ($h in $hostsToCheck) {
            Write-Host ""
            Write-Host "[curl direct] https://$h/"
            & curl.exe -sS -D - -o NUL -w "`nHTTP=%{http_code} REMOTE_IP=%{remote_ip} EXIT=%{exitcode}`n" --connect-timeout 10 --max-time 30 "https://$h/" 2>&1
            Write-Host "curl_exit_code=$LASTEXITCODE"
        }
        $proxyAddress = $null
        try {
            $internetSettings = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            if ($internetSettings.ProxyEnable -eq 1 -and $internetSettings.ProxyServer) {
                $rawProxy = [string]$internetSettings.ProxyServer
                if ($rawProxy -match "^(?:http=)?([^;]+)") { $proxyAddress = $Matches[1] }
                if ($proxyAddress -and $proxyAddress -notmatch "^[a-zA-Z][a-zA-Z0-9+.-]*://") {
                    $proxyAddress = "http://$proxyAddress"
                }
            }
        } catch {}
        if ($proxyAddress) {
            Write-Host ""
            Write-Host "[curl explicit proxy] proxy endpoint=$($proxyAddress -replace '://[^/@]+@', '://[credentials-hidden]@')"
            foreach ($h in $hostsToCheck) {
                Write-Host "[curl proxy] https://$h/"
                & curl.exe -sS -D - -o NUL -w "`nHTTP=%{http_code} REMOTE_IP=%{remote_ip} EXIT=%{exitcode}`n" --proxy $proxyAddress --connect-timeout 10 --max-time 30 "https://$h/" 2>&1
                Write-Host "curl_exit_code=$LASTEXITCODE"
            }
        } else { Write-Host "No enabled current-user proxy endpoint found; explicit proxy curl test skipped." }
    } else { Write-Host "curl.exe not found; skipped." }

    Section "7. Python httpx (direct vs explicit local proxy)"
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        Write-Host "python_path=$($python.Source)"
        $proxyForPython = $null
        try {
            $internetSettings = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            if ($internetSettings.ProxyEnable -eq 1 -and $internetSettings.ProxyServer) {
                $rawProxy = [string]$internetSettings.ProxyServer
                if ($rawProxy -match "^(?:http=)?([^;]+)") { $proxyForPython = $Matches[1] }
                if ($proxyForPython -and $proxyForPython -notmatch "^[a-zA-Z][a-zA-Z0-9+.-]*://") {
                    $proxyForPython = "http://$proxyForPython"
                }
            }
        } catch {}
        $code = @'
import httpx
import sys
print("python_version=", sys.version.replace("\\n", " "))
print("httpx_version=", httpx.__version__)
hosts = ("mineru.net", "cdn-mineru.openxlab.org.cn")
for host in hosts:
    for mode, kwargs in (("direct", {"trust_env": False}),):
        print(f"\\n[httpx] host={host} mode={mode}", flush=True)
        try:
            with httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=False, **kwargs) as client:
                response = client.get(f"https://{host}/")
            print("HTTP=", response.status_code, "server=", response.headers.get("server"), flush=True)
        except Exception as exc:
            print("FAIL:", type(exc).__name__, str(exc), flush=True)
proxy = __PROXY__
if proxy:
    for host in hosts:
        print(f"\\n[httpx] host={host} mode=explicit_proxy", flush=True)
        try:
            with httpx.Client(proxy=proxy, trust_env=False, timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=False) as client:
                response = client.get(f"https://{host}/")
            print("HTTP=", response.status_code, "server=", response.headers.get("server"), flush=True)
        except Exception as exc:
            print("FAIL:", type(exc).__name__, str(exc), flush=True)
else:
    print("No enabled current-user proxy endpoint; explicit proxy httpx test skipped.", flush=True)
'@
        $proxyLiteral = if ($proxyForPython) { "'" + $proxyForPython.Replace("\\", "\\\\").Replace("'", "\\'") + "'" } else { "None" }
        $code = $code.Replace("__PROXY__", $proxyLiteral)
        $tempPython = Join-Path $env:TEMP ("mineru-network-" + [guid]::NewGuid().ToString("N") + ".py")
        try {
            [System.IO.File]::WriteAllText($tempPython, $code, (New-Object System.Text.UTF8Encoding($false)))
            & $python.Source $tempPython 2>&1
            Write-Host "python_exit_code=$LASTEXITCODE"
        } finally {
            if (Test-Path $tempPython) { Remove-Item $tempPython -Force -ErrorAction SilentlyContinue }
        }
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
