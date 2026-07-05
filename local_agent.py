"""
Local PC Agent — runs on the user's Windows machine.
Connects to the cloud Agent Hub via WebSocket and executes local tasks.

Start with: python local_agent.py --hub wss://your-agent-hub.railway.app/ws
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import aiohttp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] local-agent: %(message)s",
)
logger = logging.getLogger("local-agent")

AGENT_ID = os.environ.get("AGENT_ID", f"pc-{platform.node()}-{uuid.uuid4().hex[:6]}")
HUB_URL = ""
HUB_TOKEN = os.environ.get("AGENT_HUB_TOKEN", "")
backoff_delay = 5  # seconds, exponential up to 300s

# ---------------------------------------------------------------------------
# Capability registry — what this PC can do
# ---------------------------------------------------------------------------
CAPABILITIES = {
    "run_command": "Execute a shell command and return output",
    "read_file": "Read a file from the local filesystem",
    "write_file": "Write content to a local file",
    "list_dir": "List directory contents",
    "git_status": "Run git status in a repo",
    "git_diff": "Run git diff in a repo",
    "run_verifiers": "Run project verifier gates (tests, lints)",
    "system_info": "Report system information (OS, CPU, memory, disk)",
    "codewhale_task": "Delegate a task to CodeWhale AI coding agent",
}


# ---------------------------------------------------------------------------
# Task execution
# ---------------------------------------------------------------------------

async def execute_task(task: dict[str, Any]) -> dict[str, Any]:
    """Execute a local task and return the result."""
    action = task.get("action", "")
    params = task.get("params", {})

    handler = _HANDLERS.get(action)
    if not handler:
        return {"status": "failed", "error": f"Unknown action: {action}", "summary": f"No handler for {action}"}

    try:
        result = await handler(params)
        return {"status": "completed", "data": result, "summary": result.get("summary", str(result)[:200])}
    except Exception as exc:
        logger.exception("Task %s failed: %s", task.get("id", "?"), action)
        return {"status": "failed", "error": str(exc), "summary": f"Failed: {exc}"}


async def _handle_run_command(params: dict[str, Any]) -> dict[str, Any]:
    command = params.get("command", "")
    cwd = params.get("cwd", os.getcwd())
    timeout = params.get("timeout", 30)

    if not command:
        return {"error": "command is required"}

    logger.info("Running: %s", command[:100])
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "command": command,
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace")[:5000],
            "stderr": stderr.decode("utf-8", errors="replace")[:2000],
        }
    except asyncio.TimeoutError:
        return {"command": command, "error": f"Timed out after {timeout}s", "exit_code": -1}
    except Exception as exc:
        return {"command": command, "error": str(exc), "exit_code": -1}


async def _handle_read_file(params: dict[str, Any]) -> dict[str, Any]:
    path = params.get("path", "")
    max_lines = params.get("max_lines", 200)

    if not path:
        return {"error": "path is required"}

    p = Path(path).expanduser().resolve()
    if not p.exists():
        return {"error": f"File not found: {p}"}

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")
        truncated = len(lines) > max_lines
        return {
            "path": str(p),
            "content": "\n".join(lines[:max_lines]),
            "total_lines": len(lines),
            "truncated": truncated,
            "size_bytes": p.stat().st_size,
        }
    except Exception as exc:
        return {"error": str(exc), "path": str(p)}


async def _handle_write_file(params: dict[str, Any]) -> dict[str, Any]:
    path = params.get("path", "")
    content = params.get("content", "")

    if not path or not content:
        return {"error": "path and content are required"}

    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"path": str(p), "size_bytes": p.stat().st_size, "status": "written"}


async def _handle_list_dir(params: dict[str, Any]) -> dict[str, Any]:
    path = params.get("path", os.getcwd())
    p = Path(path).expanduser().resolve()

    if not p.exists():
        return {"error": f"Directory not found: {p}"}

    entries = []
    for entry in sorted(p.iterdir()):
        entries.append({
            "name": entry.name,
            "is_dir": entry.is_dir(),
            "size": entry.stat().st_size if entry.is_file() else 0,
        })

    return {"path": str(p), "entries": entries[:200], "count": len(entries)}


async def _handle_git_status(params: dict[str, Any]) -> dict[str, Any]:
    repo = params.get("repo", os.getcwd())
    result = await _handle_run_command({"command": "git status --porcelain=v1 -b", "cwd": repo, "timeout": 10})
    return {"repo": repo, "git_output": result.get("stdout", ""), "error": result.get("stderr", "")}


async def _handle_git_diff(params: dict[str, Any]) -> dict[str, Any]:
    repo = params.get("repo", os.getcwd())
    result = await _handle_run_command({"command": "git diff --stat", "cwd": repo, "timeout": 15})
    return {"repo": repo, "diff_stat": result.get("stdout", ""), "error": result.get("stderr", "")}


async def _handle_run_verifiers(params: dict[str, Any]) -> dict[str, Any]:
    project = params.get("project", os.getcwd())
    verifier_type = params.get("type", "quick")

    results = {}
    if verifier_type == "quick":
        # Python syntax check
        r = await _handle_run_command({
            "command": 'python -c "import glob,ast;[ast.parse(open(f,encoding=\'utf-8\',errors=\'replace\').read()) for f in glob.glob(\'**/*.py\',recursive=True)[:100] if not any(x in f for x in [\'venv\',\'__pycache__\',\'node_modules\'])]" 2>&1 || echo "Syntax check complete"',
            "cwd": project,
            "timeout": 30,
        })
        results["syntax_check"] = {"ok": "SyntaxError" not in (r.get("stderr", "") + r.get("stdout", "")), "output": r.get("stdout", "")[:500]}

    return {"project": project, "type": verifier_type, "results": results}


async def _handle_system_info(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "node": platform.node(),
        "python": sys.version,
        "cpu_count": os.cpu_count(),
        "cwd": os.getcwd(),
        "agent_id": AGENT_ID,
        "timestamp": time.time(),
    }


async def _handle_codewhale_task(params: dict[str, Any]) -> dict[str, Any]:
    """Execute a task via CodeWhale CLI on the local machine."""
    prompt = params.get("prompt", "")
    cwd = params.get("cwd", os.getcwd())
    model = params.get("model", "")  # optional model override

    if not prompt:
        return {"error": "prompt is required", "summary": "No prompt provided for CodeWhale"}

    # Try to find codewhale CLI
    import shutil
    codewhale_bin = shutil.which("codewhale") or shutil.which("cw")

    if not codewhale_bin:
        return {
            "status": "codewhale_not_found",
            "prompt": prompt,
            "summary": "CodeWhale CLI not found on PATH. Install codewhale or set up the path.",
            "hint": "Run: npm install -g codewhale  or  pip install codewhale",
        }

    logger.info("Running CodeWhale: %s", prompt[:100])

    # Build command — codewhale typically takes a prompt as an argument
    cmd_parts = [codewhale_bin]
    if model:
        cmd_parts.extend(["--model", model])
    # Pass prompt via stdin to avoid shell escaping issues
    cmd = " ".join(cmd_parts)

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")),
            timeout=300,  # 5 minutes for CodeWhale tasks
        )

        return {
            "status": "completed" if proc.returncode == 0 else "failed",
            "exit_code": proc.returncode,
            "output": stdout.decode("utf-8", errors="replace")[:10000],
            "stderr": stderr.decode("utf-8", errors="replace")[:2000],
            "summary": f"CodeWhale completed (exit {proc.returncode})",
        }
    except asyncio.TimeoutError:
        return {
            "status": "timeout",
            "summary": "CodeWhale task timed out after 5 minutes",
            "prompt": prompt[:200],
        }
    except Exception as exc:
        return {
            "status": "error",
            "summary": f"CodeWhale execution failed: {exc}",
            "error": str(exc),
        }


_HANDLERS = {
    "run_command": _handle_run_command,
    "read_file": _handle_read_file,
    "write_file": _handle_write_file,
    "list_dir": _handle_list_dir,
    "git_status": _handle_git_status,
    "git_diff": _handle_git_diff,
    "run_verifiers": _handle_run_verifiers,
    "system_info": _handle_system_info,
    "codewhale_task": _handle_codewhale_task,
}


# ---------------------------------------------------------------------------
# WebSocket client
# ---------------------------------------------------------------------------

async def connect_to_hub(hub_url: str) -> None:
    """Connect to the Agent Hub via WebSocket and process incoming tasks."""
    global HUB_URL, backoff_delay
    HUB_URL = hub_url.rstrip("/")
    backoff_delay = 5  # start at 5s, exponential up to 5min

    # Register capabilities
    registration = {
        "type": "register",
        "agent_id": AGENT_ID,
        "agent_type": "local_pc",
        "hostname": platform.node(),
        "capabilities": CAPABILITIES,
    }

    while True:
        try:
            ws_url = HUB_URL.replace("https://", "wss://").replace("http://", "ws://") + "/ws"
            logger.info("Connecting to hub: %s", ws_url)

            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(
                    ws_url,
                    headers={"Authorization": f"Bearer {HUB_TOKEN}"} if HUB_TOKEN else {},
                ) as ws:
                    # Register
                    await ws.send_json(registration)
                    backoff_delay = 5  # reset on successful connection
                    logger.info("Registered as %s", AGENT_ID)

                    # Send initial heartbeat
                    await ws.send_json({"type": "heartbeat", "agent_id": AGENT_ID, "timestamp": time.time()})

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            msg_type = data.get("type", "")

                            if msg_type == "task":
                                task = data.get("task", {})
                                task_id = task.get("id", "?")
                                logger.info("Received task %s: %s/%s", task_id, task.get("agent", "?"), task.get("action", "?"))
                                result = await execute_task(task)
                                await ws.send_json({
                                    "type": "task_result",
                                    "task_id": task_id,
                                    "agent_id": AGENT_ID,
                                    "result": result,
                                })

                            elif msg_type == "ping":
                                await ws.send_json({"type": "pong", "agent_id": AGENT_ID, "timestamp": time.time()})

                            elif msg_type == "shutdown":
                                logger.info("Hub requested shutdown")
                                return

                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error("WebSocket error: %s", ws.exception())

        except (aiohttp.ClientError, ConnectionRefusedError, OSError) as exc:
            delay = min(backoff_delay, 300)  # cap at 5 minutes
            logger.warning("Connection lost: %s. Reconnecting in %ds...", exc, delay)
            await asyncio.sleep(delay)
            backoff_delay = min(backoff_delay * 2, 300)
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            delay = min(backoff_delay, 300)
            await asyncio.sleep(delay)
            backoff_delay = min(backoff_delay * 2, 300)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Agent Hub — Local PC Agent")
    parser.add_argument("--hub", required=True, help="Agent Hub WebSocket URL (e.g., wss://agent-hub.railway.app/ws)")
    parser.add_argument("--id", help="Agent ID (default: auto-generated)")
    parser.add_argument("--token", help="Hub auth token")

    args = parser.parse_args()

    global AGENT_ID, HUB_TOKEN
    if args.id:
        AGENT_ID = args.id
    if args.token:
        HUB_TOKEN = args.token

    logger.info("Local PC Agent starting — ID: %s", AGENT_ID)
    logger.info("Connecting to: %s", args.hub)

    try:
        asyncio.run(connect_to_hub(args.hub))
    except KeyboardInterrupt:
        logger.info("Shutting down")


if __name__ == "__main__":
    main()
