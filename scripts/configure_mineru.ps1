[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$envPath = Join-Path $repoRoot ".env"
$examplePath = Join-Path $repoRoot ".env.example"

Write-Host "MinerU API token setup"
Write-Host "Input is hidden. The token is saved locally and is not sent to GitHub."

$secureToken = Read-Host "Enter MinerU API token" -AsSecureString
if ($null -eq $secureToken -or $secureToken.Length -eq 0) {
    throw "Token cannot be empty."
}

$token = $null
$pointer = [IntPtr]::Zero

try {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)

    if (-not (Test-Path -LiteralPath $envPath)) {
        if (Test-Path -LiteralPath $examplePath) {
            Copy-Item -LiteralPath $examplePath -Destination $envPath
        }
        else {
            [System.IO.File]::WriteAllText($envPath, "")
        }
    }

    $lines = New-Object 'System.Collections.Generic.List[string]'
    if (Test-Path -LiteralPath $envPath) {
        foreach ($line in (Get-Content -LiteralPath $envPath -Encoding UTF8 -ErrorAction SilentlyContinue)) {
            [void]$lines.Add([string]$line)
        }
    }

    $tokenLine = "MINERU_TOKEN=$token"
    $found = $false

    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match '^\s*MINERU_TOKEN\s*=') {
            $lines[$index] = $tokenLine
            $found = $true
        }
    }

    if (-not $found) {
        [void]$lines.Add($tokenLine)
    }

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($envPath, $lines.ToArray(), $utf8NoBom)
}
finally {
    if ($pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }

    if ($null -ne $secureToken) {
        $secureToken.Dispose()
    }

    $token = $null
    $secureToken = $null
}

Write-Host ""
Write-Host "Token saved to the project .env file."
Write-Host "Keep .env private. It is excluded by .gitignore."
Write-Host "Restart the backend service to load the new setting."
