"""
Windows Service wrapper for Agent Hub Local Agent.
Uses pywin32 to run as a proper Windows service.

Install:
  python windows_service.py install
  python windows_service.py start
  python windows_service.py stop
  python windows_service.py remove

Or use NSSM (simpler):
  nssm install AgentHubLocalAgent
"""
import os
import sys
import time
import asyncio
import logging
from pathlib import Path

SERVICE_NAME = "AgentHubLocalAgent"
DISPLAY_NAME = "Agent Hub — Local PC Agent"
DESCRIPTION = "Connects to Agent Hub cloud and executes local tasks (file ops, git, CodeWhale, verifiers)"

# Default config
HUB_URL = os.environ.get("AGENT_HUB_URL", "wss://agent-hub-production-5ccf.up.railway.app/ws")
HUB_TOKEN = os.environ.get("AGENT_HUB_TOKEN", "agent-hub-2026-secure")

logging.basicConfig(
    filename=Path.home() / ".agent-hub" / "service.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("agent-service")


def run_service():
    """Run the local agent directly (for NSSM or Task Scheduler)."""
    logger.info("Starting Agent Hub Local Agent service")
    logger.info("Hub: %s", HUB_URL)

    # Import the local agent and run it
    agent_dir = Path(__file__).parent
    sys.path.insert(0, str(agent_dir))

    try:
        from local_agent import connect_to_hub
        asyncio.run(connect_to_hub(HUB_URL))
    except KeyboardInterrupt:
        logger.info("Service stopped by user")
    except Exception as exc:
        logger.exception("Service crashed: %s", exc)
        raise


# ---- pywin32 service class (fallback if pywin32 is installed) ----
try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager

    class AgentHubService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = DISPLAY_NAME
        _svc_description_ = DESCRIPTION

        def __init__(self, args):
            super().__init__(args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)
            logger.info("Service stop requested")

        def SvcDoRun(self):
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, "")
            )
            logger.info("Agent Hub service started via pywin32")
            run_service()

    HAS_PYWIN32 = True
except ImportError:
    HAS_PYWIN32 = False


def install_nssm():
    """Print NSSM installation instructions (simpler than pywin32)."""
    agent_script = Path(__file__).parent / "local_agent.py"
    python_exe = sys.executable

    print(f"""
╔══════════════════════════════════════════════════╗
║  Agent Hub — Local Agent Service Installation    ║
╚══════════════════════════════════════════════════╝

Option 1: NSSM (recommended, simpler)
─────────────────────────────────────
  winget install nssm
  nssm install {SERVICE_NAME} "{python_exe}" "{agent_script} --hub {HUB_URL} --token {HUB_TOKEN}"
  nssm set {SERVICE_NAME} AppDirectory "{Path(__file__).parent}"
  nssm set {SERVICE_NAME} Start SERVICE_AUTO_START
  nssm set {SERVICE_NAME} AppRestartDelay 10000
  nssm start {SERVICE_NAME}

Option 2: Task Scheduler (no install needed)
─────────────────────────────────────────────
  powershell -ExecutionPolicy Bypass -File windows_auto_start.ps1

Option 3: pywin32 service (if installed)
─────────────────────────────────────────
  python windows_service.py install
  python windows_service.py start

To check status:
  nssm status {SERVICE_NAME}
  Get-ScheduledTask AgentHub-LocalAgent | Select State

To stop:
  nssm stop {SERVICE_NAME}
  Unregister-ScheduledTask AgentHub-LocalAgent

Config:
  HUB_URL={HUB_URL}
  HUB_TOKEN={HUB_TOKEN}

Logs: {Path.home() / '.agent-hub' / 'service.log'}
""")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("install", "start", "stop", "remove", "restart"):
        if HAS_PYWIN32:
            win32serviceutil.HandleCommandLine(AgentHubService)
        else:
            print("pywin32 not installed. Run: pip install pywin32")
            print("Or use NSSM (recommended):")
            install_nssm()
    else:
        install_nssm()
        print("\nStarting agent directly (not as service)...")
        run_service()
