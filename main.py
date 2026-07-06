"""
Agent Hub — Cloud Agent Orchestrator
FastAPI backend for managing AI agents that handle email, research,
content creation, code fixes, and system maintenance.

Phase 3: Auth middleware, mobile dashboard, Lark bot setup, local agent auto-start.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

import db
from agents.base import BaseAgent
from agents.email_agent import EmailAgent
from agents.research_agent import ResearchAgent
from agents.content_agent import ContentAgent
from agents.fixit_agent import FixitAgent
from agents.orchestrator_agent import OrchestratorAgent
from agents.dev_agent import DevAgent
from agents.image_agent import ImageAgent

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agent-hub")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Agent Hub",
    version="0.3.0",
    description="Cloud agent orchestrator — email, research, content, fixes, local PC bridge, Lark bot",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Auth middleware (simple bearer token)
# ---------------------------------------------------------------------------
API_TOKEN = os.environ.get("AGENT_HUB_TOKEN", "")
PUBLIC_PATHS = {"/", "/api/health", "/api/bot/lark", "/api/bot/lark/setup", "/ws", "/favicon.ico"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Allow public paths without auth
        if path in PUBLIC_PATHS or path.startswith("/templates") or path.startswith("/static") or path.startswith("/api/bot/"):
            return await call_next(request)
        # Skip auth if no token configured
        if not API_TOKEN:
            return await call_next(request)
        # Check Authorization header
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth.removeprefix("Bearer ") != API_TOKEN:
            return Response(
                content='{"error":"unauthorized","hint":"Set Authorization: Bearer <token> header"}',
                status_code=401,
                media_type="application/json",
            )
        return await call_next(request)


app.add_middleware(AuthMiddleware)

# ---------------------------------------------------------------------------
# Agent registry
# ---------------------------------------------------------------------------
_agents: dict[str, BaseAgent] = {}
_connected_pc_agents: dict[str, WebSocket] = {}  # agent_id → websocket
_start_time: datetime | None = None


def _init_agents() -> None:
    if _agents:
        return
    _agents["email"] = EmailAgent()
    _agents["research"] = ResearchAgent()
    _agents["content"] = ContentAgent()
    _agents["fixit"] = FixitAgent()
    _agents["dev"] = DevAgent()
    _agents["image"] = ImageAgent()
    _agents["orchestrator"] = OrchestratorAgent(agent_registry=_agents)
    logger.info("Agents initialized: %s", list(_agents.keys()))


# ---------------------------------------------------------------------------
# API: Tasks (SQLite-backed)
# ---------------------------------------------------------------------------
class CreateTaskRequest(BaseModel):
    agent: str
    action: str
    params: dict[str, Any] = {}
    route_to: str | None = None  # "cloud" | "local" | agent_id
    chain: dict[str, Any] | None = None  # {"on_complete": {"agent":"...","action":"..."}, "on_failure": {...}}
    notify: dict[str, Any] | None = None  # {"webhook_url": "...", "lark_chat_id": "..."}
    reply_chat_id: str | None = None  # Lark chat ID to send results back to


@app.post("/api/tasks")
async def create_task(req: CreateTaskRequest) -> JSONResponse:
    _init_agents()

    if req.agent not in _agents:
        raise HTTPException(400, f"Unknown agent: {req.agent}. Available: {list(_agents.keys())}")

    agent = _agents[req.agent]
    caps = agent.get_capabilities()
    if req.action not in caps:
        raise HTTPException(400, f"Unknown action '{req.action}' for '{req.agent}'. Available: {list(caps.keys())}")

    task = await db.create_task(req.agent, req.action, req.params)

    # Store chain, notify, reply metadata in params for later
    meta = {}
    if req.chain:
        meta["_chain"] = req.chain
    if req.notify:
        meta["_notify"] = req.notify
    if req.reply_chat_id:
        meta["_reply_chat_id"] = req.reply_chat_id
    if meta:
        task["params"] = {**task["params"], **meta}

    # Route to local PC agent if requested
    if req.route_to == "local" and _connected_pc_agents:
        target_ws = next(iter(_connected_pc_agents.values()))
        await _dispatch_to_local(target_ws, task)
    elif req.route_to and req.route_to in _connected_pc_agents:
        await _dispatch_to_local(_connected_pc_agents[req.route_to], task)
    else:
        asyncio.create_task(_execute_cloud(task))

    logger.info("Task %s created: %s/%s", task["id"], req.agent, req.action)
    return JSONResponse(task, status_code=201)


@app.get("/api/tasks")
async def list_tasks(
    agent: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> JSONResponse:
    _init_agents()
    tasks = await db.list_tasks(agent=agent, status=status, limit=limit)
    return JSONResponse(tasks)


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str) -> JSONResponse:
    task = await db.get_task(task_id)
    if not task:
        raise HTTPException(404, f"Task not found: {task_id}")
    return JSONResponse(task)


@app.post("/api/tasks/{task_id}/approve")
async def approve_task(task_id: str) -> JSONResponse:
    task = await db.get_task(task_id)
    if not task:
        raise HTTPException(404, f"Task not found: {task_id}")
    if task["status"] != "awaiting_approval":
        raise HTTPException(400, f"Task is not awaiting approval (status: {task['status']})")

    await db.update_task(task_id, status="running")
    asyncio.create_task(_execute_cloud(task_id=task_id, approved=True))
    logger.info("Task %s approved and resumed", task_id)
    return JSONResponse({"status": "approved"})


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> JSONResponse:
    task = await db.get_task(task_id)
    if not task:
        raise HTTPException(404, f"Task not found: {task_id}")
    if task["status"] not in ("queued", "running", "awaiting_approval"):
        raise HTTPException(400, f"Cannot cancel task with status: {task['status']}")

    await db.update_task(task_id, status="failed", error="Cancelled by user")
    logger.info("Task %s cancelled", task_id)
    return JSONResponse({"status": "cancelled"})


# ---------------------------------------------------------------------------
# API: Agents
# ---------------------------------------------------------------------------
@app.get("/api/agents")
async def list_agents() -> JSONResponse:
    _init_agents()
    result = {}
    for name, agent in _agents.items():
        result[name] = {
            "name": agent.name,
            "codename": getattr(agent, "codename", name),
            "emoji": getattr(agent, "emoji", "🤖"),
            "color": getattr(agent, "color", "#3b82f6"),
            "personality": getattr(agent, "personality", ""),
            "description": agent.description,
            "capabilities": agent.get_capabilities(),
        }
    return JSONResponse(result)


@app.get("/api/local-agents")
async def list_local_agents() -> JSONResponse:
    return JSONResponse({
        "count": len(_connected_pc_agents),
        "agents": list(_connected_pc_agents.keys()),
    })


# ---------------------------------------------------------------------------
# API: Workflow Templates
# ---------------------------------------------------------------------------
WORKFLOW_TEMPLATES = {
    "morning_briefing": {
        "name": "Morning Briefing",
        "description": "Check email, get news, summarize your day ahead",
        "steps": [
            {"agent": "email", "action": "check_inbox", "params": {"limit": 5}},
            {"agent": "research", "action": "search", "params": {"query": "top technology news today", "num_results": 3}},
        ],
    },
    "deep_research_report": {
        "name": "Deep Research Report",
        "description": "Research a topic in depth and generate a formatted report",
        "steps": [
            {"agent": "research", "action": "deep_research", "params": {}, "chain_to_next": True},
            {"agent": "content", "action": "format_report", "params": {}, "chain_to_next": True},
        ],
    },
    "code_review_pipeline": {
        "name": "Code Review Pipeline",
        "description": "Analyze code, check security, suggest improvements",
        "steps": [
            {"agent": "fixit", "action": "analyze_code", "params": {}},
            {"agent": "fixit", "action": "security_audit", "params": {}},
            {"agent": "fixit", "action": "refactor", "params": {}},
        ],
    },
    "inbox_triage": {
        "name": "Inbox Triage & Reply",
        "description": "Categorize your inbox and draft replies to urgent emails",
        "steps": [
            {"agent": "email", "action": "triage_inbox", "params": {"limit": 20}},
        ],
    },
    "content_pipeline": {
        "name": "Content Creation Pipeline",
        "description": "Research a topic and create a blog post about it",
        "steps": [
            {"agent": "research", "action": "search", "params": {}, "chain_to_next": True},
            {"agent": "content", "action": "write_blog_post", "params": {}, "chain_to_next": True},
        ],
    },
    "security_scan": {
        "name": "Security Scan",
        "description": "Full security audit of code + generate fix suggestions",
        "steps": [
            {"agent": "fixit", "action": "security_audit", "params": {}},
            {"agent": "fixit", "action": "suggest_fix", "params": {}, "chain_to_next": True},
        ],
    },
}


@app.get("/api/templates")
async def list_templates() -> JSONResponse:
    """List available workflow templates."""
    return JSONResponse({
        name: {"name": t["name"], "description": t["description"], "steps": len(t["steps"])}
        for name, t in WORKFLOW_TEMPLATES.items()
    })


@app.post("/api/templates/{template_name}/run")
async def run_template(template_name: str) -> JSONResponse:
    """Execute a workflow template — creates a chain of tasks."""
    template = WORKFLOW_TEMPLATES.get(template_name)
    if not template:
        raise HTTPException(404, f"Template not found: {template_name}. Available: {list(WORKFLOW_TEMPLATES.keys())}")

    _init_agents()
    task_ids = []

    for i, step in enumerate(template["steps"]):
        is_last = (i == len(template["steps"]) - 1)
        chain = None

        if step.get("chain_to_next") and not is_last:
            next_step = template["steps"][i + 1]
            chain = {"on_complete": {"agent": next_step["agent"], "action": next_step["action"], "params": next_step.get("params", {})}}

        task = await db.create_task(step["agent"], step["action"], step.get("params", {}))
        if chain:
            await db.update_task(task["id"], params={**step.get("params", {}), "_chain": chain})

        task_ids.append(task["id"])

        if i == 0:  # Only kick off the first task — chaining handles the rest
            asyncio.create_task(_execute_cloud(task))

    return JSONResponse({
        "status": "started",
        "template": template_name,
        "task_ids": task_ids,
        "steps": len(task_ids),
    }, status_code=201)


# ---------------------------------------------------------------------------
# API: Health
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health() -> dict[str, Any]:
    total = await db.get_task_count()
    active = await db.get_task_count("queued") + await db.get_task_count("running")
    return {
        "status": "ok",
        "version": "0.3.0",
        "auth_enabled": bool(API_TOKEN),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agents": list(_agents.keys()) if _agents else [],
        "local_agents": len(_connected_pc_agents),
        "tasks_total": total,
        "tasks_active": active,
        "db": db.DB_PATH,
        "uptime_seconds": (datetime.now(timezone.utc) - _start_time).total_seconds() if _start_time else 0,
    }


# ---------------------------------------------------------------------------
# Telegram Bot webhook
# ---------------------------------------------------------------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


@app.post("/api/bot/telegram")
async def telegram_webhook(request: Request) -> JSONResponse:
    """Receive commands from a Telegram bot and create tasks. Replies with results."""
    _init_agents()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    message = body.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id", "")
    text = (message.get("text", "") or "").strip()

    if not text or not chat_id:
        return JSONResponse({"status": "no action"})

    # Parse: "/agents research search python async" or just "/search python"
    text = text.lstrip("/")
    if text.startswith("agents "):
        text = text[7:]
    parts = text.split(maxsplit=1)

    if not parts:
        return JSONResponse({"status": "unknown command"})

    agent_name = parts[0].lower()

    # If the first word isn't a known agent, treat the whole thing as a natural language goal
    if agent_name not in _agents:
        # Route to orchestrator for intelligent handling
        task = await db.create_task("orchestrator", "solve", {"goal": text})
        params = {"_reply_telegram_chat_id": str(chat_id)}
        await db.update_task(task["id"], params=params)
        asyncio.create_task(_execute_cloud(task))
        await _send_telegram(chat_id, f"🤔 Thinking about: {text[:200]}...")
        return JSONResponse({"status": "ok", "task_id": task["id"], "routed_to": "orchestrator"})

    action_and_params = parts[1] if len(parts) > 1 else ""

    # Parse action
    action_parts = action_and_params.split(maxsplit=1)
    action = action_parts[0] if action_parts else list(_agents[agent_name].get_capabilities().keys())[0]
    query = action_parts[1] if len(action_parts) > 1 else ""

    params = {}
    if action in ("search", "deep_research", "compare", "check_inbox", "search_emails",
                   "create_doc", "create_spreadsheet", "create_slides", "write_blog_post",
                   "format_report", "analyze_code", "suggest_fix", "explain_code"):
        params["query"] = query
    elif action == "draft_reply":
        params["thread_id"] = query

    task = await db.create_task(agent_name, action, params)
    params["_reply_telegram_chat_id"] = str(chat_id)
    await db.update_task(task["id"], params=params)

    asyncio.create_task(_execute_cloud(task))
    await _send_telegram(chat_id, f"⏳ Working on: {agent_name}/{action}... Task {task['id'][:8]}")
    return JSONResponse({"status": "ok", "task_id": task["id"]})


async def _send_telegram(chat_id: str | int, text: str) -> None:
    """Send a message via Telegram bot."""
    if not TELEGRAM_TOKEN:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text[:4000], "parse_mode": "Markdown"},
            )
    except Exception as exc:
        logger.warning("Telegram send failed: %s", exc)


@app.get("/api/bot/telegram/setup")
async def telegram_setup_info() -> JSONResponse:
    base_url = os.environ.get("BASE_URL", "https://agent-hub.railway.app")
    return JSONResponse({
        "setup_steps": [
            "1. Open Telegram and message @BotFather",
            "2. Send /newbot and follow prompts",
            "3. Copy the bot token",
            "4. Set TELEGRAM_BOT_TOKEN on Railway",
            f"5. Set webhook: curl https://api.telegram.org/bot<TOKEN>/setWebhook?url={base_url}/api/bot/telegram",
            "6. Message your bot!",
        ],
        "webhook_url": f"{base_url}/api/bot/telegram",
        "commands": [
            "/research search <query>", "/research deep_research <query>",
            "/email check_inbox", "/email search_emails <query>",
            "/content write_blog_post <topic>", "/content create_doc <topic>",
            "/fixit analyze_code", "/fixit explain_code",
        ],
    })


# ---------------------------------------------------------------------------
# Lark Bot webhook (backward compat)
# ---------------------------------------------------------------------------
@app.post("/api/bot/lark")
async def lark_bot_webhook(request: Request) -> JSONResponse:
    """Receive commands from a Lark bot and create tasks."""
    _init_agents()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    # Handle URL verification challenge
    if body.get("type") == "url_verification":
        return JSONResponse({"challenge": body.get("challenge", "")})

    # Extract message text
    event = body.get("event", {})
    text = event.get("text", "").strip()

    if not text:
        return JSONResponse({"status": "no action"})

    # Parse command: "/agents email check_inbox" or "research search python async"
    text = text.lstrip("/").lstrip("agents").strip()
    parts = text.split(maxsplit=1)

    if not parts:
        return JSONResponse({"status": "unknown command", "text": text})

    agent_name = parts[0].lower()
    action_and_params = parts[1] if len(parts) > 1 else ""

    if agent_name not in _agents:
        available = ", ".join(_agents.keys())
        return JSONResponse({
            "status": "unknown_agent",
            "text": f"Unknown agent: {agent_name}. Available: {available}",
        })

    # Determine action and params
    action_parts = action_and_params.split(maxsplit=1)
    action = action_parts[0] if action_parts else list(_agents[agent_name].get_capabilities().keys())[0]
    query = action_parts[1] if len(action_parts) > 1 else ""

    params = {}
    if action in ("search", "deep_research", "compare", "check_inbox", "search_emails",
                   "create_doc", "create_spreadsheet", "create_slides", "write_blog_post",
                   "format_report", "analyze_code", "suggest_fix", "explain_code"):
        params["query"] = query
    elif action == "draft_reply":
        params["thread_id"] = query

    # Get chat_id for reply
    chat_id = event.get("message", {}).get("chat_id", "") or body.get("event", {}).get("sender", {}).get("sender_id", {}).get("open_id", "")

    task = await db.create_task(agent_name, action, params)

    # Store reply metadata so the bot can respond when done
    if chat_id:
        params["_reply_chat_id"] = chat_id
        await db.update_task(task["id"], params=params)

    asyncio.create_task(_execute_cloud(task))

    # Send immediate acknowledgment
    asyncio.create_task(_send_lark_reply(chat_id, task, {
        "status": "running",
        "summary": f"⏳ Working on: {agent_name}/{action}... Task {task['id'][:8]}",
    }))

    return JSONResponse({
        "status": "task_created",
        "task_id": task["id"],
        "agent": agent_name,
        "action": action,
    })


@app.get("/api/bot/lark/setup")
async def lark_bot_setup_info() -> JSONResponse:
    """Return Lark bot setup instructions and event subscription info."""
    base_url = os.environ.get("BASE_URL", "https://agent-hub.railway.app")
    return JSONResponse({
        "webhook_url": f"{base_url}/api/bot/lark",
        "verification_note": "This endpoint handles Lark's URL verification challenge automatically.",
        "setup_steps": [
            "1. Go to https://open.feishu.cn/app and create a Bot app",
            "2. Under 'Event Subscriptions', set the Request URL to the webhook_url above",
            "3. Subscribe to 'im.message.receive_v1' event",
            "4. Add bot permissions: im:message, im:message:send_as_bot",
            "5. Publish the app and add the bot to a chat",
            "6. Send commands like: /agents email check_inbox",
        ],
        "supported_commands": [
            "/agents email check_inbox — check inbox",
            "/agents email draft_reply <thread_id> — draft a reply",
            "/agents email search_emails <query> — search emails",
            "/agents research search <query> — web search",
            "/agents research deep_research <query> — multi-step research",
            "/agents content create_doc <topic> — create a document",
            "/agents content write_blog_post <topic> — write a blog post",
            "/agents fixit analyze_code — analyze code (paste code after)",
            "/agents fixit suggest_fix <error> — suggest a fix",
        ],
    })


# ---------------------------------------------------------------------------
# WebSocket: Local PC Agent bridge
# ---------------------------------------------------------------------------
@app.websocket("/ws")
async def ws_local_agent(ws: WebSocket) -> None:
    """WebSocket endpoint for local PC agents to connect and receive tasks."""
    await ws.accept()
    agent_id = "unknown"
    agent_info: dict[str, Any] = {}

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "register":
                agent_id = data.get("agent_id", f"pc-{uuid.uuid4().hex[:6]}")
                agent_info = data
                _connected_pc_agents[agent_id] = ws
                logger.info("Local agent connected: %s (host: %s)", agent_id, agent_info.get("hostname", "?"))

                # Acknowledge registration
                await ws.send_json({
                    "type": "registered",
                    "agent_id": agent_id,
                    "message": f"Connected to Agent Hub. {len(_connected_pc_agents)} local agent(s) online.",
                })

            elif msg_type == "task_result":
                task_id = data.get("task_id", "")
                result = data.get("result", {})
                if task_id:
                    status = "completed" if result.get("status") == "completed" else "failed"
                    await db.update_task(task_id, status=status, result=result)
                    logger.info("Task %s result from %s: %s", task_id, agent_id, status)

            elif msg_type == "heartbeat":
                pass  # Keepalive — no action needed

            elif msg_type == "pong":
                pass

    except WebSocketDisconnect:
        logger.info("Local agent disconnected: %s", agent_id)
    except Exception as exc:
        logger.exception("WebSocket error for %s: %s", agent_id, exc)
    finally:
        _connected_pc_agents.pop(agent_id, None)


async def _dispatch_to_local(ws: WebSocket, task: dict[str, Any]) -> None:
    """Send a task to a connected local PC agent."""
    try:
        await ws.send_json({"type": "task", "task": task})
        await db.update_task(task["id"], status="running")
    except Exception as exc:
        logger.warning("Failed to dispatch task %s to local agent: %s", task["id"], exc)
        await db.update_task(task["id"], status="failed", error=f"Dispatch failed: {exc}")


# ---------------------------------------------------------------------------
# File output — download agent results as files
# ---------------------------------------------------------------------------
@app.get("/api/files/{task_id}")
async def download_file(task_id: str, format: str = "txt") -> Response:
    task = await db.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    result = task.get("result") or {}
    summary = result.get("summary", "")
    data = result.get("data") or {}
    content = summary

    # Try to get richer content from data
    if data.get("code"):
        content = data["code"]
        ext = {"python": "py", "javascript": "js", "bash": "sh"}.get(data.get("language", ""), "txt")
    elif data.get("markdown"):
        content = data["markdown"]
        ext = "md"
    elif data.get("svg_code"):
        content = data["svg_code"]
        ext = "svg"
    elif format == "json":
        content = json.dumps(result, indent=2, default=str)
        ext = "json"
    else:
        ext = "txt"

    filename = f"{task['agent']}_{task['action']}_{task_id[:8]}.{ext}"
    return Response(content=content, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ---------------------------------------------------------------------------
# WebSocket dashboard — real-time task feed
# ---------------------------------------------------------------------------
_dashboard_clients: list[WebSocket] = []


@app.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket):
    await ws.accept()
    _dashboard_clients.append(ws)
    try:
        while True:
            await ws.receive_text()  # keepalive
    except Exception:
        pass
    finally:
        _dashboard_clients.remove(ws)


async def _broadcast_dashboard(msg: dict) -> None:
    """Push a task update to all connected dashboard clients."""
    dead = []
    for ws in _dashboard_clients:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _dashboard_clients.remove(ws)


async def _on_task_completed(task: dict[str, Any], result: dict[str, Any]) -> None:
    """Handle post-completion: chain next task, fire notifications, reply to Lark."""
    params = task.get("params", {})
    tid = task["id"]

    # 1. Task chaining
    chain = params.get("_chain")
    if chain:
        next_task = chain.get("on_complete")
        if next_task:
            # Merge result data into next task params
            next_params = {**next_task.get("params", {}), "_parent_result": result}
            nt = await db.create_task(next_task["agent"], next_task["action"], next_params)
            asyncio.create_task(_execute_cloud(nt))
            logger.info("Chain: task %s → %s/%s (%s)", tid, next_task["agent"], next_task["action"], nt["id"])

    # 2. Notification webhooks
    notify = params.get("_notify")
    if notify:
        webhook_url = notify.get("webhook_url")
        if webhook_url:
            asyncio.create_task(_fire_webhook(webhook_url, task, result))

    # 3. Lark bot reply (backward compat)
    chat_id = params.get("_reply_chat_id")
    if chat_id:
        asyncio.create_task(_send_lark_reply(chat_id, task, result))

    # 4. Telegram bot reply
    tg_chat_id = params.get("_reply_telegram_chat_id")
    if tg_chat_id:
        summary = str(result.get("summary", "Done"))[:1000]
        status_emoji = "✅" if result.get("status") == "completed" else "❌"
        asyncio.create_task(_send_telegram(tg_chat_id, f"{status_emoji} **{task['agent']}/{task['action']}**\n\n{summary}"))

    # 5. Save to memory
    asyncio.create_task(db.save_memory(tid, "assistant", str(result.get("summary", ""))[:2000]))

    # 6. Broadcast to dashboard
    asyncio.create_task(_broadcast_dashboard({"type": "task_update", "task": {**task, "result": result}}))


async def _on_task_failed(task: dict[str, Any], error: str) -> None:
    """Handle post-failure: chain failure handler, notify."""
    params = task.get("params", {})
    tid = task["id"]

    chain = params.get("_chain")
    if chain:
        fallback = chain.get("on_failure")
        if fallback:
            fb_params = {**fallback.get("params", {}), "_error": error}
            nt = await db.create_task(fallback["agent"], fallback["action"], fb_params)
            asyncio.create_task(_execute_cloud(nt))
            logger.info("Chain (failure): task %s → fallback %s/%s", tid, fallback["agent"], fallback["action"])

    notify = params.get("_notify")
    if notify:
        webhook_url = notify.get("webhook_url")
        if webhook_url:
            asyncio.create_task(_fire_webhook(webhook_url, task, {"status": "failed", "error": error}))

    chat_id = params.get("_reply_chat_id")
    if chat_id:
        asyncio.create_task(_send_lark_reply(chat_id, task, {"status": "failed", "summary": f"❌ Failed: {error[:200]}"}))


async def _fire_webhook(url: str, task: dict[str, Any], result: dict[str, Any]) -> None:
    """Fire a notification webhook — auto-detects Slack/Discord format."""
    try:
        import httpx

        is_slack = "slack.com" in url or "hooks.slack" in url
        is_discord = "discord.com" in url
        is_success = result.get("status") == "completed"
        emoji = "✅" if is_success else "❌"

        if is_slack:
            payload = {
                "blocks": [
                    {"type": "header", "text": {"type": "plain_text", "text": f"{emoji} {task['agent']}/{task['action']}"}},
                    {"type": "section", "text": {"type": "mrkdwn", "text": str(result.get("summary", "No output"))[:2900]}},
                    {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Task `{task['id']}` · {datetime.now(timezone.utc).isoformat()[:19]}Z"}]},
                ]
            }
        elif is_discord:
            payload = {
                "embeds": [{
                    "title": f"{emoji} {task['agent']}/{task['action']}",
                    "description": str(result.get("summary", ""))[:2000],
                    "color": 0x22C55E if is_success else 0xEF4444,
                    "footer": {"text": f"Task {task['id']}"},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }]
            }
        else:
            payload = {
                "event": "task_completed" if is_success else "task_failed",
                "task_id": task["id"],
                "agent": task["agent"],
                "action": task["action"],
                "summary": str(result.get("summary", ""))[:500],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            logger.info("Webhook %s → %d", url[:60], resp.status_code)
    except Exception as exc:
        logger.warning("Webhook failed for %s: %s", url[:60], exc)


async def _send_lark_reply(chat_id: str, task: dict[str, Any], result: dict[str, Any]) -> None:
    """Send a task result back to a Lark chat."""
    lark_app_id = os.environ.get("LARK_APP_ID", "")
    lark_app_secret = os.environ.get("LARK_APP_SECRET", "")

    if not lark_app_id or not lark_app_secret:
        logger.debug("Lark reply skipped — no LARK_APP_ID/SECRET configured")
        return

    try:
        import httpx

        # Get tenant access token
        async with httpx.AsyncClient(timeout=10) as client:
            token_resp = await client.post(
                "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": lark_app_id, "app_secret": lark_app_secret},
            )
            if token_resp.status_code != 200:
                return
            token = token_resp.json().get("tenant_access_token", "")

            # Build message
            summary = str(result.get("summary", "Done"))[:800]
            status_emoji = "✅" if result.get("status") == "completed" else "❌"
            msg_text = f"{status_emoji} **{task['agent']}/{task['action']}** complete\n\n{summary}"

            # Send message
            msg_resp = await client.post(
                "https://open.larksuite.com/open-apis/im/v1/messages",
                params={"receive_id_type": "chat_id"},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "receive_id": chat_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": msg_text}),
                },
            )
            logger.info("Lark reply to %s → %d", chat_id[:20], msg_resp.status_code)
    except Exception as exc:
        logger.warning("Lark reply failed: %s", exc)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
_scheduler_started = False


async def _start_scheduler() -> None:
    """Start APScheduler for recurring tasks if enabled."""
    global _scheduler_started
    if _scheduler_started:
        return
    if os.environ.get("SCHEDULER_ENABLED", "true").lower() not in ("true", "1", "yes"):
        return
    _scheduler_started = True

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = AsyncIOScheduler()
        briefing_time = os.environ.get("DAILY_BRIEFING_TIME", "08:00")
        hour, minute = briefing_time.split(":")
        scheduler.add_job(
            _daily_briefing,
            CronTrigger(hour=int(hour), minute=int(minute)),
            id="daily_briefing",
            name="Daily briefing",
        )
        # Hourly cleanup of old tasks
        scheduler.add_job(
            lambda: db.cleanup_old_tasks(30),
            CronTrigger(hour="*/6"),
            id="cleanup_old_tasks",
            name="Cleanup old tasks",
        )
        scheduler.start()
        logger.info("Scheduler started (daily briefing at %s UTC, cleanup every 6h)", briefing_time)
    except ImportError:
        logger.warning("apscheduler not installed — scheduler disabled")
    except Exception as exc:
        logger.warning("Scheduler failed to start: %s", exc)


async def _daily_briefing() -> None:
    """Autonomous daily briefing — checks email, news, and alerts if needed."""
    _init_agents()
    try:
        # Smart email triage
        email_task = await db.create_task("email", "triage_inbox", {"limit": 15})
        asyncio.create_task(_execute_cloud(email_task))

        # News briefing
        news_task = await db.create_task("research", "news_briefing", {"query": "AI and technology"})
        asyncio.create_task(_execute_cloud(news_task))

        # If Telegram token set, send briefing there
        if TELEGRAM_TOKEN:
            # Find urgent emails and notify
            asyncio.create_task(_autonomous_alert())

        logger.info("Autonomous briefing created: %s, %s", email_task["id"], news_task["id"])
    except Exception as exc:
        logger.exception("Autonomous briefing failed: %s", exc)


async def _autonomous_alert() -> None:
    """Proactively alert the user about urgent items."""
    try:
        # Check for urgent emails
        email_result = await db.list_tasks(agent="email", status="completed", limit=3)
        for t in email_result:
            result = t.get("result") or {}
            data = result.get("data") or {}
            urgent = data.get("categories", {}).get("urgent", [])
            if urgent:
                await _send_telegram(
                    os.environ.get("TELEGRAM_ALERT_CHAT_ID", ""),
                    f"⚠️ {len(urgent)} urgent email(s) detected. Check your inbox."
                )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Auto-retry failed tasks
# ---------------------------------------------------------------------------
async def _execute_cloud(task=None, task_id=None, approved=False, retry_count=0) -> None:
    """Execute with auto-retry on failure."""
    if task_id and not task:
        task = await db.get_task(task_id)
    if not task:
        return

    tid = task["id"]
    params = task.get("params", {})
    await db.update_task(tid, status="running")

    agent = _agents.get(task["agent"])
    if not agent:
        await db.update_task(tid, status="failed", error=f"Agent '{task['agent']}' not found")
        return

    try:
        result = await agent.execute(action=task["action"], params=params)

        if result.get("status") == "awaiting_approval":
            await db.update_task(tid, status="awaiting_approval", result=result)
            return

        await db.update_task(tid, status="completed", result=result)
        asyncio.create_task(_on_task_completed(task, result))

    except Exception as exc:
        logger.exception("Task %s failed (attempt %d)", tid, retry_count + 1)

        if retry_count < 2:  # Auto-retry up to 2 times
            logger.info("Retrying task %s in %ds...", tid, (retry_count + 1) * 10)
            await asyncio.sleep((retry_count + 1) * 10)
            await _execute_cloud(task=task, retry_count=retry_count + 1)
        else:
            await db.update_task(tid, status="failed", error=str(exc))
            asyncio.create_task(_on_task_failed(task, str(exc)))


# ---------------------------------------------------------------------------
# Analytics API
# ---------------------------------------------------------------------------
@app.get("/api/analytics")
async def analytics() -> JSONResponse:
    """Return agent performance stats."""
    all_tasks = await db.list_tasks(limit=500)
    stats = {"total": len(all_tasks), "by_agent": {}, "by_status": {}, "recent_failures": 0}

    for t in all_tasks:
        agent = t["agent"]
        status = t["status"]
        if agent not in stats["by_agent"]:
            stats["by_agent"][agent] = {"total": 0, "completed": 0, "failed": 0}
        stats["by_agent"][agent]["total"] += 1
        if status == "completed":
            stats["by_agent"][agent]["completed"] += 1
        elif status == "failed":
            stats["by_agent"][agent]["failed"] += 1

        stats["by_status"][status] = stats["by_status"].get(status, 0) + 1

    # Success rate
    for a in stats["by_agent"]:
        ag = stats["by_agent"][a]
        ag["success_rate"] = round(ag["completed"] / max(ag["total"], 1) * 100, 1)

    # Recent failures
    stats["recent_failures"] = sum(1 for t in all_tasks[:100] if t["status"] == "failed")

    # Popular actions
    actions = {}
    for t in all_tasks[:200]:
        key = f"{t['agent']}/{t['action']}"
        actions[key] = actions.get(key, 0) + 1
    stats["popular_actions"] = dict(sorted(actions.items(), key=lambda x: x[1], reverse=True)[:10])

    return JSONResponse(stats)


# ---------------------------------------------------------------------------
# Webhook triggers — external services fire agent workflows
# ---------------------------------------------------------------------------
TRIGGERS = {
    "github_push": {"agent": "fixit", "action": "review_pr", "params": {}},
    "new_email": {"agent": "email", "action": "triage_inbox", "params": {"limit": 10}},
    "daily_report": {"agent": "orchestrator", "action": "plan_and_execute", "params": {"goal": "research AI news and create a summary report"}},
}


@app.post("/api/triggers/{trigger_name}")
async def fire_trigger(trigger_name: str, request: Request) -> JSONResponse:
    """Fire a pre-configured workflow from an external webhook."""
    trigger = TRIGGERS.get(trigger_name)
    if not trigger:
        raise HTTPException(404, f"Trigger not found: {trigger_name}. Available: {list(TRIGGERS.keys())}")

    # Merge request body into params
    try:
        body = await request.json()
    except Exception:
        body = {}

    params = {**trigger["params"], **body}
    task = await db.create_task(trigger["agent"], trigger["action"], params)
    asyncio.create_task(_execute_cloud(task))

    logger.info("Trigger '%s' fired → task %s", trigger_name, task["id"])
    return JSONResponse({"status": "triggered", "task_id": task["id"], "trigger": trigger_name}, status_code=201)


@app.get("/api/triggers")
async def list_triggers() -> JSONResponse:
    return JSONResponse({name: {"agent": t["agent"], "action": t["action"]} for name, t in TRIGGERS.items()})


# ---------------------------------------------------------------------------
# Conversation memory API
# ---------------------------------------------------------------------------
@app.get("/api/memory/{task_id}")
async def get_memory(task_id: str) -> JSONResponse:
    mem = await db.get_memory(task_id)
    return JSONResponse({"task_id": task_id, "memory": mem, "count": len(mem)})


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup() -> None:
    """Initialize database and scheduler on startup."""
    global _start_time
    _start_time = datetime.now(timezone.utc)
    await db.get_db()  # Ensure migrations run
    _init_agents()
    await _start_scheduler()
    logger.info("Agent Hub v0.3.0 started")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await db.close_db()
    logger.info("Agent Hub shut down")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    template_path = Path(__file__).parent / "templates" / "dashboard.html"
    return HTMLResponse(template_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "5679"))
    uvicorn.run(app, host="0.0.0.0", port=port)
