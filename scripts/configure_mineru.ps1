[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$envPath = Join-Path $repoRoot ".env"
$examplePath = Join-Path $repoRoot ".env.example"

Write-Host "MinerU v4 Token 本地配置"
Write-Host "输入内容不会回显，也不会发送到 GitHub。"

$secureToken = Read-Host "请输入 MinerU API Token" -AsSecureString
if ($secureToken.Length -eq 0) {
    throw "Token 不能为空。"
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
            New-Item -ItemType File -Path $envPath | Out-Null
        }
    }

    $lines = @(Get-Content -LiteralPath $envPath -ErrorAction SilentlyContinue)
    $tokenLine = "MINERU_TOKEN=$token"
    $found = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match '^\s*MINERU_TOKEN=') {
            $lines[$index] = $tokenLine
            $found = $true
        }
    }
    if (-not $found) {
        $lines += $tokenLine
    }

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($envPath, $lines, $utf8NoBom)
}
finally {
    if ($pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    if ($secureToken) {
        $secureToken.Dispose()
    }
    $token = $null
    $secureToken = $null
}

Write-Host ""
Write-Host "已将 Token 保存到项目根目录 .env。"
Write-Host "该文件已被 .gitignore 排除；请勿手动提交或分享它。"
Write-Host "重启后端服务后，MinerU 配置即可生效。"
