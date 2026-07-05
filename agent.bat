@echo off
REM Agent Hub CLI — drop this folder on PATH or run directly
REM Usage:
REM   agent research search "python async"
REM   agent "what's new in AI today"
REM   agent --repl
REM   agent --status
REM   agent --list

set AGENT_HUB_URL=https://agent-hub-production-5ccf.up.railway.app
set AGENT_HUB_TOKEN=agent-hub-2026-secure
set PYTHONUTF8=1

"%~dp0.venv\Scripts\python.exe" "%~dp0agent" %*
