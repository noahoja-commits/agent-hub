#!/usr/bin/env python3
"""
Agent Hub CLI — command your agents from the terminal.

Usage:
  agent research search "latest AI news"     # structured command
  agent "what's new in Python 3.14"          # natural language → orchestrator
  agent --repl                                # interactive mode
  agent --list                                # list available agents
  agent --status                              # show hub status

Setup:
  pip install agent-hub-cli
  agent --config https://agent-hub.railway.app your-token-here
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

CONFIG_DIR = Path.home() / ".agent-hub"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Try color support
try:
    import colorama
    colorama.init()
    C = {"R": "\033[91m", "G": "\033[92m", "Y": "\033[93m", "B": "\033[94m",
         "M": "\033[95m", "C": "\033[96m", "W": "\033[0m", "D": "\033[90m"}
except ImportError:
    C = {k: "" for k in "RGYBM CWD"}


def load_config() -> dict:
    """Load config from file or env."""
    config = {
        "base_url": os.environ.get("AGENT_HUB_URL", "https://agent-hub-production-5ccf.up.railway.app"),
        "token": os.environ.get("AGENT_HUB_TOKEN", ""),
    }
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text())
            config.update(saved)
        except Exception:
            pass
    return config


def save_config(base_url: str, token: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({"base_url": base_url, "token": token}, indent=2))


def api(method: str, path: str, data: dict | None = None, config: dict | None = None) -> tuple:
    """Make an API request to agent-hub."""
    cfg = config or load_config()
    url = f"{cfg['base_url']}{path}"
    body = json.dumps(data).encode() if data else None
    headers = {}
    if cfg.get("token"):
        headers["Authorization"] = f"Bearer {cfg['token']}"
    if body:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return json.loads(r.read()), r.status, None
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read()), e.code, None
        except Exception:
            return None, e.code, str(e)
    except Exception as e:
        return None, 0, str(e)


def spinner(msg: str, stop_event: list):
    """Simple spinner while waiting."""
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    i = 0
    while not stop_event[0]:
        sys.stderr.write(f"\r{C['B']}{frames[i % len(frames)]}{C['W']} {msg}")
        sys.stderr.flush()
        time.sleep(0.1)
        i += 1
    sys.stderr.write("\r" + " " * (len(msg) + 4) + "\r")
    sys.stderr.flush()


def run_task(agent: str, action: str, params: dict | None = None, config: dict | None = None) -> None:
    """Create a task and wait for the result."""
    cfg = config or load_config()
    data = {"agent": agent, "action": action, "params": params or {}}

    # Create task
    task, status, err = api("POST", "/api/tasks", data, cfg)
    if err or not task:
        print(f"{C['R']}Error creating task: {err or status}{C['W']}")
        return

    tid = task["id"]
    print(f"{C['D']}Task {tid[:8]} {C['M']}{agent}/{action}{C['W']} ", end="", flush=True)

    # Wait for completion with spinner
    stop = [False]
    import threading
    t = threading.Thread(target=spinner, args=("thinking...", stop), daemon=True)
    t.start()

    max_wait = 120  # seconds
    result = None
    for _ in range(max_wait * 2):  # poll every 0.5s
        time.sleep(0.5)
        result, s, _ = api("GET", f"/api/tasks/{tid}", None, cfg)
        if result and result.get("status") in ("completed", "failed", "awaiting_approval"):
            break

    stop[0] = True
    time.sleep(0.2)

    if not result:
        print(f"\n{C['R']}Timed out waiting for result{C['W']}")
        return

    status = result.get("status", "?")
    r = result.get("result") or {}
    summary = r.get("summary", result.get("error", "No output"))

    if status == "completed":
        print(f"{C['G']}✓{C['W']}")
    elif status == "awaiting_approval":
        print(f"{C['Y']}⚠ Needs approval{C['W']} — open dashboard to approve")
    else:
        print(f"{C['R']}✗{C['W']}")

    print(f"\n{C['W']}{summary}{C['W']}")

    # Show data if --verbose
    if "--verbose" in sys.argv or "-v" in sys.argv:
        data_payload = r.get("data")
        if data_payload:
            print(f"\n{C['D']}── Data ──{C['W']}")
            print(json.dumps(data_payload, indent=2, default=str)[:2000])


def run_natural(query: str, config: dict | None = None) -> None:
    """Send a natural language query to the orchestrator."""
    run_task("orchestrator", "solve", {"goal": query}, config)


def list_agents(config: dict | None = None) -> None:
    """List available agents and their actions."""
    cfg = config or load_config()
    agents, status, err = api("GET", "/api/agents", None, cfg)

    if err or not agents:
        print(f"{C['R']}Failed to fetch agents: {err or status}{C['W']}")
        print(f"{C['D']}Check: {cfg.get('base_url', '?')} is reachable and your token is valid{C['W']}")
        return

    print(f"{C['B']}Available agents:{C['W']}\n")
    for name, a in agents.items():
        caps = a.get("capabilities", {})
        print(f"  {C['M']}{a['name']}{C['W']} — {a.get('description', '')[:70]}")
        for action, desc in caps.items():
            print(f"    {C['G']}{action:<22}{C['W']} {desc[:60]}")
        print()


def show_status(config: dict | None = None) -> None:
    """Show hub health status."""
    cfg = config or load_config()
    h, status, err = api("GET", "/api/health", None, cfg)

    if err or not h:
        print(f"{C['R']}Cannot reach agent-hub at {cfg.get('base_url', '?')}{C['W']}")
        print(f"{C['D']}Error: {err or status}{C['W']}")
        return

    status_color = C['G'] if h.get("status") == "ok" else C['R']
    print(f"  Status:      {status_color}{h.get('status', '?')}{C['W']}")
    print(f"  Version:     {h.get('version', '?')}")
    print(f"  URL:         {cfg.get('base_url', '?')}")
    print(f"  Auth:        {'enabled' if h.get('auth_enabled') else 'disabled'}")
    print(f"  Cloud agents:{len(h.get('agents', []))}")
    print(f"  Local agents:{h.get('local_agents', 0)} online")
    print(f"  Tasks:       {h.get('tasks_active', 0)} active / {h.get('tasks_total', 0)} total")
    print(f"  Uptime:      {h.get('uptime_seconds', 0):.0f}s")


def repl(config: dict | None = None) -> None:
    """Interactive REPL mode."""
    cfg = config or load_config()

    # Try to use readline for history
    try:
        import readline
        hist_file = CONFIG_DIR / "history"
        if hist_file.exists():
            readline.read_history_file(str(hist_file))
    except Exception:
        pass

    print(f"{C['B']}╔══════════════════════════════════════╗{C['W']}")
    print(f"{C['B']}║   Agent Hub — Interactive Terminal   ║{C['W']}")
    print(f"{C['B']}╚══════════════════════════════════════╝{C['W']}")
    print(f"{C['D']}Connected to: {cfg.get('base_url', '?')}{C['W']}")
    print(f"{C['D']}Type {C['W']}help{C['D']} for commands, {C['W']}quit{C['D']} to exit{C['W']}\n")

    try:
        import readline
        readline.set_history_length(1000)
    except Exception:
        pass

    while True:
        try:
            cmd = input(f"{C['G']}agent>{C['W']} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not cmd:
            continue
        if cmd.lower() in ("quit", "exit", "q"):
            break
        if cmd.lower() == "help":
            print(f"""
{C['B']}Commands:{C['W']}
  {C['G']}<agent> <action> <query>{C['W']}  — run a specific agent action
  {C['G']}<natural language>{C['W']}       — orchestrator figures out what to do
  {C['G']}list{C['W']} or {C['G']}ls{C['W']}              — list available agents
  {C['G']}status{C['W']} or {C['G']}st{C['W']}            — show hub status
  {C['G']}tasks{C['W']}                    — show recent tasks
  {C['G']}config <url> <token>{C['W']}     — save API credentials
  {C['G']}quit{C['W']} or {C['G']}exit{C['W']}           — exit

{C['D']}Examples:{C['W']}
  research search latest AI news
  email check_inbox
  find the best Python web framework and compare them
  fixit explain_code def hello(): print('world')
""")
            continue
        if cmd.lower() in ("list", "ls"):
            list_agents(cfg)
            continue
        if cmd.lower() in ("status", "st"):
            show_status(cfg)
            continue
        if cmd.lower() == "tasks":
            tasks, s, _ = api("GET", "/api/tasks?limit=10", None, cfg)
            if tasks:
                for t in tasks:
                    icon = {"completed": "✓", "failed": "✗", "running": "…", "queued": "○"}.get(t["status"], "?")
                    print(f"  {icon} {t['id'][:8]} {t['agent']}/{t['action']} [{t['status']}]")
            else:
                print(f"  {C['D']}No tasks{C['W']}")
            continue
        if cmd.lower().startswith("config "):
            parts = cmd.split()
            if len(parts) >= 3:
                save_config(parts[1], parts[2])
                cfg = load_config()
                print(f"{C['G']}Config saved: {parts[1]}{C['W']}")
            else:
                print(f"{C['D']}Usage: config <url> <token>{C['W']}")
            continue

        # Parse: "agent action query" or natural language
        parts = cmd.split(maxsplit=2)
        first = parts[0].lower()

        # If first word is a known agent, use structured mode
        known_agents = set()
        try:
            agents, _, _ = api("GET", "/api/agents", None, cfg)
            if agents:
                known_agents = set(agents.keys())
        except Exception:
            pass

        if first in known_agents:
            agent_name = first
            action = parts[1] if len(parts) > 1 else ""
            query = parts[2] if len(parts) > 2 else ""
            params = {"query": query} if query else {}
            if action:
                run_task(agent_name, action, params, cfg)
            else:
                print(f"{C['D']}Usage: {agent_name} <action> [query]{C['W']}")
                caps = agents[agent_name].get("capabilities", {})
                for a in caps:
                    print(f"  {C['G']}{a}{C['W']}")
        else:
            # Natural language → orchestrator
            run_natural(cmd, cfg)

    # Save history
    try:
        import readline
        readline.write_history_file(str(CONFIG_DIR / "history"))
    except Exception:
        pass
    print(f"{C['D']}Bye!{C['W']}")


def main():
    args = sys.argv[1:]

    # Help
    if not args or "--help" in args or "-h" in args:
        print(__doc__)
        sys.exit(0)

    # Load config
    config = load_config()

    # Config management
    if args[0] == "--config":
        if len(args) >= 3:
            save_config(args[1], args[2])
            print(f"{C['G']}Config saved.{C['W']}")
        else:
            print(f"Usage: agent --config <base_url> <token>")
            print(f"Current: {config.get('base_url', 'not set')}")
        return

    # List agents
    if "--list" in args or "-l" in args:
        list_agents(config)
        return

    # Status
    if "--status" in args or "-s" in args:
        show_status(config)
        return

    # REPL mode
    if "--repl" in args or "-i" in args:
        repl(config)
        return

    # Parse command
    query = " ".join(args)

    # If it looks like "agent action query", use structured mode
    parts = query.split(maxsplit=2)
    first = parts[0].lower()

    known_agents = {"research", "email", "content", "fixit", "orchestrator"}
    # Also try fetching from API
    try:
        agents, _, _ = api("GET", "/api/agents", None, config)
        if agents:
            known_agents = set(agents.keys())
    except Exception:
        pass

    if first in known_agents:
        agent_name = first
        action = parts[1] if len(parts) > 1 else ""
        q = parts[2] if len(parts) > 2 else ""
        params = {"query": q} if q else {}
        if action:
            run_task(agent_name, action, params, config)
        else:
            print(f"{C['R']}Missing action. Available:{C['W']}")
            try:
                caps = agents[agent_name].get("capabilities", {})
                for a, d in caps.items():
                    print(f"  {C['G']}{a}{C['W']} — {d}")
            except Exception:
                pass
    else:
        # Natural language
        run_natural(query, config)


if __name__ == "__main__":
    main()
