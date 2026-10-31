param(
    [string]$ImageTag = 'whisper-agent:torch2.13-cu132',
    [ValidateSet('ask', 'project', 'global', 'custom', 'skip')]
    [string]$SkillScope = 'ask',
    [string]$SkillProjectDirectory,
    [string]$SkillsDirectory,
    [switch]$OverwriteSkill
)

$ErrorActionPreference = 'Stop'
$sourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).ProviderPath
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

# Ask before the long image build, so the choice is not hidden after installation.
if ($SkillScope -eq 'ask') {
    Write-Host 'Install the independent name-speakers skill:'
    Write-Host '  project - project .agents/skills; global - home .agents/skills'
    Write-Host '  custom - another agent skills directory; skip - service only'
    $SkillScope = (Read-Host 'Choose project, global, custom or skip').Trim().ToLowerInvariant()
    if ($SkillScope -notin @('project', 'global', 'custom', 'skip')) { throw 'Choose a valid skill installation scope.' }
}
if ($SkillScope -eq 'project' -and -not $SkillProjectDirectory) {
    $SkillProjectDirectory = Read-Host 'Absolute project directory for the skill'
}
if ($SkillScope -eq 'custom' -and -not $SkillsDirectory) {
    $SkillsDirectory = Read-Host 'Absolute skills directory of your agent'
}
if ($SkillScope -ne 'skip') {
    $skillArgs = @((Join-Path $sourceRoot 'scripts\install-skill.mjs'), '--scope', $SkillScope)
    if ($SkillScope -eq 'project') { $skillArgs += @('--project-dir', $SkillProjectDirectory) }
    if ($SkillScope -eq 'custom') { $skillArgs += @('--skills-dir', $SkillsDirectory) }
    if ($OverwriteSkill) { $skillArgs += '--overwrite' }
    & node @skillArgs
    if ($LASTEXITCODE -ne 0) { throw 'Skill installation failed. Existing skills are preserved unless -OverwriteSkill was specified.' }
    Write-Host 'The skill is installed independently; it remains usable if service installation fails.'
}

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
$pluginRoot = Join-Path $installRoot 'claude-plugin'
$pluginManifest = Join-Path $pluginRoot '.claude-plugin'
New-Item -ItemType Directory -Path $pluginManifest -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $sourceRoot 'integrations\claude-plugin\.mcp.json') -Destination $pluginRoot -Force
Copy-Item -LiteralPath (Join-Path $sourceRoot 'integrations\claude-plugin\.claude-plugin\plugin.json') -Destination $pluginManifest -Force
Copy-Item -LiteralPath (Join-Path $sourceRoot 'scripts\connect-windows.ps1') -Destination $installRoot -Force

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
Write-Host "Cowork plugin folder: $pluginRoot"
Write-Host "Connect agents: powershell -ExecutionPolicy Bypass -File `"$(Join-Path $installRoot 'connect-windows.ps1')`""
