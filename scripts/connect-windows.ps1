param()

$ErrorActionPreference = 'Stop'
if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is not set.' }
$agentRoot = Join-Path $env:LOCALAPPDATA 'WhisperAgent'
$mcpPath = Join-Path $agentRoot 'src\mcp.mjs'
if (-not (Test-Path -LiteralPath $mcpPath -PathType Leaf)) {
    throw "Whisper MCP is not installed at $mcpPath. Run install-windows.ps1 first."
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Node.js was not found in PATH.' }

function Write-Utf8File([string]$Path, [string]$Content) {
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Invoke-AgentCli([string]$Executable, [string[]]$Arguments, [switch]$Quiet) {
    # PowerShell 5.1 can turn a native process's stderr into a terminating error
    # when ErrorActionPreference is Stop. A missing MCP entry is expected here.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($Quiet) {
            & $Executable @Arguments *> $null
        } else {
            & $Executable @Arguments | Out-Host
        }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

if (Get-Command codex -ErrorAction SilentlyContinue) {
    if ((Invoke-AgentCli 'codex' @('mcp', 'get', 'whisper-agent') -Quiet) -eq 0) {
        Write-Host 'Codex: whisper-agent is already configured; kept existing settings.'
    } else {
        if ((Invoke-AgentCli 'codex' @('mcp', 'add', 'whisper-agent', '--', 'node', $mcpPath)) -ne 0) {
            throw 'Could not add whisper-agent to Codex.'
        }
        $codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
        $codexConfig = Join-Path $codexHome 'config.toml'
        $configText = [System.IO.File]::ReadAllText($codexConfig)
        $heading = '(?m)^\[mcp_servers\.(?:whisper-agent|"whisper-agent")\][ \t]*\r?\n'
        $section = [regex]::Match($configText, $heading)
        if (-not $section.Success) {
            throw "Codex added the server, but its config section was not found in $codexConfig. Set tool_timeout_sec = 3600 manually."
        }
        Copy-Item -LiteralPath $codexConfig -Destination "$codexConfig.bak-$(Get-Date -Format yyyyMMdd-HHmmss)" -Force
        $configText = $configText.Insert($section.Index + $section.Length, "tool_timeout_sec = 3600`r`n")
        Write-Utf8File $codexConfig $configText
        Write-Host 'Codex: connected with a 3600-second transcription timeout.'
    }
} else {
    Write-Warning 'Codex CLI was not found; configure Codex from its MCP settings using the command shown below.'
}

if (Get-Command claude -ErrorAction SilentlyContinue) {
    if ((Invoke-AgentCli 'claude' @('mcp', 'get', 'whisper-agent') -Quiet) -eq 0) {
        Write-Host 'Claude Code: whisper-agent is already configured; kept existing settings.'
    } else {
        $server = @{ type = 'stdio'; command = 'node'; args = @($mcpPath); timeout = 3600000 } | ConvertTo-Json -Compress
        if ((Invoke-AgentCli 'claude' @('mcp', 'add-json', '--scope', 'user', 'whisper-agent', $server)) -ne 0) {
            throw 'Could not add whisper-agent to Claude Code.'
        }
        Write-Host 'Claude Code: connected with a 3600-second transcription timeout.'
    }
} else {
    Write-Warning 'Claude Code CLI was not found; configure Claude Code from its MCP settings using the command shown below.'
}

if (Get-Command opencode -ErrorAction SilentlyContinue) {
    if ($env:OPENCODE_CONFIG) {
        Write-Warning 'OPENCODE_CONFIG is set; a custom config may override the global MCP entry.'
    }
    $configDir = Join-Path $env:USERPROFILE '.config\opencode'
    $configPath = Join-Path $configDir 'opencode.json'
    $jsoncPath = Join-Path $configDir 'opencode.jsonc'
    if (Test-Path -LiteralPath $jsoncPath -PathType Leaf) {
        Write-Warning "OpenCode uses $jsoncPath. Add the MCP entry there manually; this script will not rewrite a JSONC file."
    } else {
        $versionText = (& opencode --version).Trim()
        if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '^(\d+)\.') {
            Write-Warning 'OpenCode version could not be determined; skipped its configuration.'
        } else {
            $majorVersion = [int]$Matches[1]
            New-Item -ItemType Directory -Path $configDir -Force | Out-Null
            if (Test-Path -LiteralPath $configPath -PathType Leaf) {
                try { $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json }
                catch { Write-Warning "Could not parse $configPath; skipped OpenCode to preserve it."; $config = $null }
            } else {
                $config = [pscustomobject]@{ '$schema' = 'https://opencode.ai/config.json' }
            }
            if ($null -ne $config) {
                if (-not ($config -is [pscustomobject])) { throw "OpenCode config is not a JSON object: $configPath" }
                if (-not $config.PSObject.Properties['mcp']) {
                    $config | Add-Member -NotePropertyName mcp -NotePropertyValue ([pscustomobject]@{})
                }
                if (-not ($config.mcp -is [pscustomobject])) { throw "OpenCode mcp setting is not a JSON object: $configPath" }
                $servers = $config.mcp
                if ($majorVersion -ge 2) {
                    if (-not $config.mcp.PSObject.Properties['servers']) {
                        $config.mcp | Add-Member -NotePropertyName servers -NotePropertyValue ([pscustomobject]@{})
                    }
                    $servers = $config.mcp.servers
                }
                if (-not ($servers -is [pscustomobject])) { throw "OpenCode MCP servers setting is not a JSON object: $configPath" }
                if ($servers.PSObject.Properties['whisper-agent']) {
                    Write-Host 'OpenCode: whisper-agent is already configured; kept existing settings.'
                } else {
                    $entry = [pscustomobject]@{ type = 'local'; command = @('node', $mcpPath); timeout = 3600000 }
                    if ($majorVersion -ge 2) {
                        $entry | Add-Member -NotePropertyName disabled -NotePropertyValue $false
                    } else {
                        $entry | Add-Member -NotePropertyName enabled -NotePropertyValue $true
                    }
                    $servers | Add-Member -NotePropertyName 'whisper-agent' -NotePropertyValue $entry
                    if (Test-Path -LiteralPath $configPath -PathType Leaf) {
                        Copy-Item -LiteralPath $configPath -Destination "$configPath.bak-$(Get-Date -Format yyyyMMdd-HHmmss)" -Force
                    }
                    Write-Utf8File $configPath ($config | ConvertTo-Json -Depth 100)
                    Write-Host "OpenCode: connected in $configPath."
                }
            }
        }
    }
} else {
    Write-Warning 'OpenCode CLI was not found; skipped its configuration.'
}

Write-Host "MCP launch command: node `"$mcpPath`""
Write-Host 'MCP starts automatically when a connected agent needs it; no separate Docker container stays running.'
Write-Host "Cowork: upload the plugin folder at $(Join-Path $agentRoot 'claude-plugin') in Claude Desktop."
