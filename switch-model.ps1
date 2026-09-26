param (
    [string]$ModelChoice = ""
)

# GLM model switcher for Claude Code via Z.ai
#
# Auth token lives in .claude/settings.local.json and is preserved when
# switching. This script only rewrites the model mapping env entries.

$AvailableModels = [ordered]@{
    "1" = @{ Name = "GLM-5.3 (Flagship - best for coding)";        Id = "glm-5.3" }
    "2" = @{ Name = "GLM-5.2";                                     Id = "glm-5.2" }
    "3" = @{ Name = "GLM-5.1";                                     Id = "glm-5.1" }
    "4" = @{ Name = "GLM-5-Turbo";                                 Id = "glm-5-turbo" }
    "5" = @{ Name = "GLM-5.3-Flash (Fast, low cost)";              Id = "glm-5.3-flash" }
    "6" = @{ Name = "GLM-4.7";                                     Id = "glm-4.7" }
    "7" = @{ Name = "GLM-4.6";                                     Id = "glm-4.6" }
}

$Selected = $null

if ($ModelChoice -ne "") {
    if ($AvailableModels.Contains($ModelChoice)) {
        $Selected = $AvailableModels[$ModelChoice]
    } else {
        foreach ($k in $AvailableModels.Keys) {
            if ($AvailableModels[$k].Id -like "*$ModelChoice*" -or $AvailableModels[$k].Name -like "*$ModelChoice*") {
                $Selected = $AvailableModels[$k]
                break
            }
        }
    }
}

if ($null -eq $Selected) {
    Write-Host "`n=== Z.ai GLM Models ===" -ForegroundColor Cyan
    foreach ($k in $AvailableModels.Keys) {
        Write-Host "$k) $($AvailableModels[$k].Name)"
    }

    $inputChoice = Read-Host "`nSelect a model [1-7] (default: 1)"
    if ([string]::IsNullOrWhiteSpace($inputChoice)) { $inputChoice = "1" }
    if ($AvailableModels.Contains($inputChoice)) {
        $Selected = $AvailableModels[$inputChoice]
    } else {
        $Selected = $AvailableModels["1"]
    }
}

Write-Host "`nConfiguring model: $($Selected.Name) [$($Selected.Id)]" -ForegroundColor Green

$localSettingsPath = Join-Path $PSScriptRoot ".claude\settings.local.json"
if (-not (Test-Path $localSettingsPath)) {
    Write-Host "ERROR: $localSettingsPath not found." -ForegroundColor Red
    exit 1
}

$settings = Get-Content $localSettingsPath -Raw | ConvertFrom-Json
$settings.env.ANTHROPIC_BASE_URL = "https://api.z.ai/api/anthropic"
$settings.env.ANTHROPIC_MODEL = $Selected.Id
$settings.env.ANTHROPIC_DEFAULT_SONNET_MODEL = $Selected.Id
$settings.env.ANTHROPIC_DEFAULT_OPUS_MODEL = $Selected.Id
$settings.env.ANTHROPIC_DEFAULT_FABLE_MODEL = $Selected.Id
$settings.env.ANTHROPIC_DEFAULT_HAIKU_MODEL = "glm-5.3-flash"
$settings.env.CLAUDE_CODE_SUBAGENT_MODEL = "glm-5.3-flash"
$settings | ConvertTo-Json -Depth 10 | Set-Content -Path $localSettingsPath -Encoding UTF8

$projectSettingsPath = Join-Path $PSScriptRoot ".claude\settings.json"
if (Test-Path $projectSettingsPath) {
    $projectSettings = Get-Content $projectSettingsPath -Raw | ConvertFrom-Json
    $projectSettings.env.ANTHROPIC_MODEL = $Selected.Id
    $projectSettings.env.ANTHROPIC_DEFAULT_SONNET_MODEL = $Selected.Id
    $projectSettings.env.ANTHROPIC_DEFAULT_OPUS_MODEL = $Selected.Id
    $projectSettings.env.ANTHROPIC_DEFAULT_FABLE_MODEL = $Selected.Id
    $projectSettings | ConvertTo-Json -Depth 10 | Set-Content -Path $projectSettingsPath -Encoding UTF8
}

Write-Host "Launching Claude Code..." -ForegroundColor Cyan
claude --model $Selected.Id
