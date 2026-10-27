param(
    [string]$ImageTag = 'whisper-agent:torch2.13-cu132'
)

$ErrorActionPreference = 'Stop'
$sourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is not set.' }
$installRoot = Join-Path $env:LOCALAPPDATA 'WhisperAgent'
foreach ($command in @('node', 'npm', 'docker')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command was not found in PATH. Install Node.js 20+ and Docker Desktop first."
    }
}
$nodeVersion = (& node --version).Trim()
if ($LASTEXITCODE -ne 0 -or $nodeVersion -notmatch '^v(\d+)\.') { throw 'Could not determine Node.js version.' }
if ([int]$Matches[1] -lt 20) { throw "Node.js 20+ is required; found $nodeVersion." }

& docker info --format '{{.ServerVersion}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is not running or is unavailable.' }

New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
foreach ($name in @('src', 'container')) {
    $destination = Join-Path $installRoot $name
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    Copy-Item -Path (Join-Path $sourceRoot "$name/*") -Destination $destination -Recurse -Force
}
foreach ($name in @('Dockerfile', '.dockerignore', 'package.json', 'package-lock.json')) {
    Copy-Item -LiteralPath (Join-Path $sourceRoot $name) -Destination $installRoot -Force
}

& npm.cmd ci --prefix $installRoot
if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
& docker build -t $ImageTag $installRoot
if ($LASTEXITCODE -ne 0) { throw 'Docker image build failed.' }
& docker run --rm --gpus all $ImageTag python -c 'import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))'
if ($LASTEXITCODE -ne 0) { throw 'CUDA GPU check failed in the Whisper image.' }

$mcpPath = Join-Path $installRoot 'src\mcp.mjs'
$cliPath = Join-Path $installRoot 'src\cli.mjs'
Write-Host "Installed runtime: $installRoot"
Write-Host "MCP command: node `"$mcpPath`""
Write-Host "CLI command: node `"$cliPath`" --help"
Write-Host "Run log: $(Join-Path $installRoot 'runs.jsonl')"
