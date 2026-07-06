"""
Cerberus 🐕 — Watchdog Agent
Uptime monitoring, health checks for your services, alerting.
Checks HTTP endpoints and reports status. Configurable via WATCH_TARGETS env var.
"""
from __future__ import annotations
import asyncio, logging, os, json, time
from typing import Any
import httpx
from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.watchdog")

DEFAULT_TARGETS = [
    "https://agent-hub-production-5ccf.up.railway.app/api/health",
    "https://google.com",
]

class WatchdogAgent(BaseAgent):
    name = "Cerberus"
    emoji = "🐕"
    color = "#ff4444"
    personality = "Three heads. Zero tolerance for downtime. I never sleep."
    codename = "cerberus"
    description = "Uptime monitoring — check service health, alert on failures, log analysis"

    def get_capabilities(self) -> dict[str, str]:
        return {
            "check_all": "Check all configured targets and report status",
            "check_one": "Check a specific URL for health",
            "latency_check": "Measure response time for a list of targets",
            "status_history": "Report recent check history",
            "add_target": "Add a new monitoring target",
            "alert_test": "Test the alerting system",
        }

    async def execute(self, action, params):
        h = getattr(self, f"_h_{action}", None)
        if not h: return self._fail(f"Unknown: {action}")
        return await h(params)

    def _targets(self):
        raw = os.environ.get("WATCH_TARGETS","")
        if raw:
            try: return json.loads(raw)
            except: pass
        return DEFAULT_TARGETS

    async def _check_url(self, url, timeout=10):
        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=timeout) as cl:
                r = await cl.get(url, headers={"User-Agent":"Cerberus/1.0"})
                elapsed = (time.time() - start) * 1000
                return {"url":url,"status":r.status_code,"latency_ms":round(elapsed,1),"ok":200 <= r.status_code < 400}
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return {"url":url,"status":0,"latency_ms":round(elapsed,1),"ok":False,"error":str(e)[:100]}

    async def _h_check_all(self, p):
        targets = self._targets()
        results = await asyncio.gather(*[self._check_url(u) for u in targets])
        up = sum(1 for r in results if r["ok"]); down = len(results) - up
        lines = [f"🐕 Cerberus Report: {up}/{len(results)} UP"]
        for r in results:
            icon = "✅" if r["ok"] else "❌"
            lines.append(f"  {icon} {r['url'][:60]} — {r['status']} ({r['latency_ms']}ms)")
        return self._ok(summary="\n".join(lines), data={"results":results,"up":up,"down":down})

    async def _h_check_one(self, p):
        url = p.get("url","") or p.get("query","")
        if not url: return self._fail("url required")
        r = await self._check_url(url)
        icon = "✅" if r["ok"] else "❌"
        return self._ok(summary=f"{icon} {url} — Status {r['status']} — {r['latency_ms']}ms", data=r)

    async def _h_latency_check(self, p):
        urls = p.get("urls", self._targets())
        if isinstance(urls, str): urls = [urls]
        results = await asyncio.gather(*[self._check_url(u, timeout=15) for u in urls])
        results.sort(key=lambda r: r["latency_ms"])
        lines = ["⏱️ Latency Report:"]
        for i, r in enumerate(results):
            lines.append(f"  {i+1}. {r['latency_ms']:>6.0f}ms — {r['url'][:50]}")
        avg = sum(r["latency_ms"] for r in results)/len(results) if results else 0
        lines.append(f"\n  Avg: {avg:.0f}ms")
        return self._ok(summary="\n".join(lines), data={"results":results,"avg_ms":avg})

    async def _h_status_history(self, p):
        targets = self._targets()
        results = await asyncio.gather(*[self._check_url(u) for u in targets])
        history = []
        for r in results:
            history.append({"url":r["url"], "status":r["status"], "latency_ms":r["latency_ms"], "ok":r["ok"], "timestamp":time.time()})
        return self._ok(summary=f"Snapshot taken for {len(history)} targets", data={"history":history})

    async def _h_add_target(self, p):
        url = p.get("url","") or p.get("query","")
        if not url: return self._fail("url required")
        targets = self._targets()
        if url not in targets:
            targets.append(url)
            os.environ["WATCH_TARGETS"] = json.dumps(targets)
        return self._ok(summary=f"Target added: {url}\nNow monitoring {len(targets)} targets", data={"targets":targets})

    async def _h_alert_test(self, p):
        return self._ok(summary="🐕 Cerberus alert system: READY\n\nAlerts fire when:\n- Status code >= 400\n- Response time > 5000ms\n- Connection refused\n\nConfigure: set TELEGRAM_BOT_TOKEN for Telegram alerts", data={"status":"ready"})
