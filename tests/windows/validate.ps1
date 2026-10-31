param([Parameter(Mandatory=$true)][string]$Repository)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Path (Join-Path $Repository 'test-results') -Force | Out-Null
$taskRoot = Join-Path ([IO.Path]::GetTempPath()) ('whisper-txt-validation-' + [guid]::NewGuid())
$originalToken = $env:HF_TOKEN
$originalLogPath = $env:WHISPER_LOG_PATH
New-Item -ItemType Directory -Path $taskRoot | Out-Null
try {
    $runtime = Join-Path $env:LOCALAPPDATA 'WhisperAgent'
    $env:HF_TOKEN = [Environment]::GetEnvironmentVariable('HF_TOKEN', 'User')
    if (-not $env:HF_TOKEN) { throw 'HF_TOKEN is missing' }
    $env:WHISPER_LOG_PATH = Join-Path $taskRoot 'runs.jsonl'
    $project = Join-Path $taskRoot 'project'
    New-Item -ItemType Directory -Path $project | Out-Null
    Add-Type -AssemblyName System.Speech
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    try {
        $voice = $synth.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'ru-RU' } | Select-Object -First 1
        if (-not $voice) { throw 'Russian TTS voice unavailable' }
        $synth.SelectVoice($voice.VoiceInfo.Name)
        $synth.SetOutputToWaveFile((Join-Path $project 'russian-synthetic.wav'))
        $synth.Speak('Это короткая проверка распознавания русской речи. Сегодня мы проверяем работу программы и разделение записи по участникам. Результат должен сохраниться в отдельном файле.')
    } finally { $synth.Dispose() }
    & node (Join-Path $Repository 'tests\windows\mcp-validation.mjs') $runtime $project (Join-Path $taskRoot 'output') (Join-Path $Repository 'test-results\windows-txt.json')
    if ($LASTEXITCODE -ne 0) { throw 'Windows MCP TXT validation failed' }
} finally {
    $env:HF_TOKEN = $originalToken
    $env:WHISPER_LOG_PATH = $originalLogPath
    & node -e "require('node:fs').rmSync(process.argv[1], { recursive: true, force: true, maxRetries: 2 })" $taskRoot
    if ($LASTEXITCODE -ne 0) { throw 'Temporary directory cleanup failed' }
}
