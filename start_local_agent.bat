@echo off
REM Agent Hub — Local Agent Quick Start
REM Double-click this to start the local agent (console window stays open)
REM Edit the variables below before first use.

set HUB_URL=wss://agent-hub.railway.app/ws
set HUB_TOKEN=change-me

cd /d "%~dp0"
.\.venv\Scripts\python.exe local_agent.py --hub %HUB_URL% --token %HUB_TOKEN%
pause
