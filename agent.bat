@echo off
REM Agent Hub CLI — drop this folder on PATH or run directly
REM Usage:
REM   agent research search "python async"
REM   agent "what's new in AI today"
REM   agent --repl
REM   agent --status
REM   agent --list

set AGENT_HUB_URL=https://abyssal-terminal-production.up.railway.app
set PYTHONUTF8=1

"%~dp0.venv\Scripts\python.exe" "%~dp0agent" %*
