# Windows Auto-Start: Register Local PC Agent as a Scheduled Task
# Run this script ONCE as Administrator to set up auto-start.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File windows_auto_start.ps1
#
# This creates a scheduled task that starts the local agent at logon
# and keeps it running. Edit the variables below first.

param(
    [string]$HubUrl = "wss://agent-hub.railway.app/ws",
    [string]$Token = "change-me",
    [string]$AgentId = "",
    [string]$PythonPath = ".\.venv\Scripts\python.exe",
    [string]$AgentScript = "local_agent.py"
)

$ErrorActionPreference = "Stop"
$TaskName = "AgentHub-LocalAgent"

# Resolve paths relative to this script's directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonFull = Join-Path $ScriptDir $PythonPath
$AgentFull = Join-Path $ScriptDir $AgentScript

if (-not (Test-Path $PythonFull)) {
    Write-Error "Python not found at: $PythonFull"
    Write-Host "Install with: cd $ScriptDir; uv venv; uv pip install -r requirements.txt"
    exit 1
}

# Build arguments
$Args = @("`"$AgentFull`"", "--hub", $HubUrl)
if ($Token -ne "change-me") { $Args += "--token"; $Args += $Token }
if ($AgentId) { $Args += "--id"; $Args += $AgentId }
$ArgumentString = $Args -join " "

# Remove existing task if present
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task: $TaskName"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Create scheduled task
$Action = New-ScheduledTaskAction -Execute $PythonFull -Argument $ArgumentString -WorkingDirectory $ScriptDir
$Trigger = New-ScheduledTaskTrigger -AtLogon
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 99 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "Agent Hub Local PC Agent — connects to cloud hub for remote task execution" `
    -Force

# Start immediately
Start-ScheduledTask -TaskName $TaskName

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Agent Hub Local Agent — AUTO-START ENABLED" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Task name : $TaskName"
Write-Host "Hub URL   : $HubUrl"
Write-Host "Agent ID  : $(if ($AgentId) { $AgentId } else { 'auto-generated' })"
Write-Host ""
Write-Host "The agent will start automatically when you log in and reconnect if it drops."
Write-Host ""
Write-Host "To check status:"
Write-Host "  Get-ScheduledTask -TaskName '$TaskName' | Select State"
Write-Host ""
Write-Host "To stop/remove:"
Write-Host "  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
Write-Host ""
Write-Host "Logs are written to stdout. To capture logs to a file:"
Write-Host "  Edit the scheduled task and append '2>&1 > C:\Users\$env:USERNAME\agent-hub\agent.log' to arguments"
