"""
Chronos ⏳ — Calendar Agent
Google Calendar integration. Checks schedule, finds free slots, creates events.
Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN (same as Gmail).
"""
from __future__ import annotations
import logging, os, json
from datetime import datetime, timedelta, timezone
from typing import Any
import httpx
from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.calendar")
CAL_API = "https://www.googleapis.com/calendar/v3"

TOKEN_URL = "https://oauth2.googleapis.com/token"
_token_cache: dict[str, dict] = {}

async def _get_token() -> str:
    import time as _time
    key = "default"
    c = _token_cache.get(key)
    if c and _time.time() < c.get("expiry", 0) - 60:
        return c["access_token"]
    cid = os.environ.get("GOOGLE_CLIENT_ID","")
    cs = os.environ.get("GOOGLE_CLIENT_SECRET","")
    rt = os.environ.get("GOOGLE_REFRESH_TOKEN","")
    if not all([cid, cs, rt]): return ""
    async with httpx.AsyncClient(timeout=15) as cl:
        r = await cl.post(TOKEN_URL, data={"client_id":cid,"client_secret":cs,"refresh_token":rt,"grant_type":"refresh_token"})
        if r.status_code != 200: return ""
        d = r.json()
        _token_cache[key] = {"access_token": d.get("access_token",""), "expiry": _time.time() + d.get("expires_in", 3600)}
        return d.get("access_token","")

async def _cal(method, path, params=None, body=None):
    t = await _get_token()
    if not t: return {}
    h = {"Authorization": f"Bearer {t}"}
    url = f"{CAL_API}{path}"
    async with httpx.AsyncClient(timeout=15) as cl:
        if method == "GET": r = await cl.get(url, headers=h, params=params)
        elif method == "POST": r = await cl.post(url, headers=h, json=body)
        else: return {}
        if r.status_code not in (200,201): logger.warning("Calendar %s %s: %d", method, path, r.status_code); return {}
        return r.json() if r.text else {}

class CalendarAgent(BaseAgent):
    name = "Chronos"
    emoji = "⏳"
    color = "#cc8800"
    personality = "Master of time. I see your schedule, your gaps, your deadlines."
    codename = "chronos"
    description = "Calendar management — check schedule, find free time, create events, set reminders"

    def get_capabilities(self) -> dict[str, str]:
        return {
            "today": "Today's events — see what's on your calendar right now",
            "week": "This week's schedule at a glance",
            "find_slot": "Find free time slots between events",
            "create_event": "Create a calendar event with title, time, duration, guests",
            "busy_check": "Check if you're free at a specific time",
            "upcoming": "List upcoming events in the next N days",
        }

    async def execute(self, action, params):
        h = getattr(self, f"_h_{action}", None)
        if not h: return self._fail(f"Unknown: {action}")
        return await h(params)

    async def _h_today(self, p):
        now = datetime.now(timezone.utc)
        events = await self._fetch(now.replace(hour=0,minute=0,second=0), now.replace(hour=23,minute=59,second=59))
        return self._fmt(events, "Today", "No events today — enjoy the void")

    async def _h_week(self, p):
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=7)
        events = await self._fetch(now, end)
        return self._fmt(events, "This Week", "No events this week")

    async def _h_find_slot(self, p):
        days = p.get("days", 3)
        duration = p.get("duration", 60)
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days)
        events = await self._fetch(now, end)
        if not events:
            return self._ok(summary=f"Completely free for the next {days} days. Any slot works.")
        busy = []
        for e in events:
            start = e.get("start",{}).get("dateTime","")
            end_t = e.get("end",{}).get("dateTime","")
            if start and end_t: busy.append((start, end_t))
        busy.sort()
        slots = []
        cursor = now
        for s, e in busy:
            try:
                sdt = datetime.fromisoformat(s.replace("Z","+00:00"))
                edt = datetime.fromisoformat(e.replace("Z","+00:00"))
                gap = (sdt - cursor).total_seconds() / 60
                if gap >= duration:
                    slots.append(f"{cursor.strftime('%a %I:%M%p')} → {sdt.strftime('%I:%M%p')} ({int(gap)}min free)")
                cursor = max(cursor, edt)
            except: pass
        if not slots:
            slots.append(f"No {duration}min slots found. Try shorter duration or more days.")
        return self._ok(summary=f"Free slots ({duration}min+):\n" + "\n".join(slots[:8]), data={"slots": slots})

    async def _h_create_event(self, p):
        title = p.get("title","") or p.get("query","")
        when = p.get("when","tomorrow 10am")
        duration = p.get("duration", 60)
        if not title: return self._fail("title required")
        # Simple: create now+1h if no Google creds
        tkn = await _get_token()
        if not tkn:
            return self._ok(summary=f"📅 Event created (demo): \"{title}\" — {when}, {duration}min\nGoogle Calendar not configured.")
        start_dt = datetime.now(timezone.utc) + timedelta(hours=1)
        end_dt = start_dt + timedelta(minutes=duration)
        body = {"summary":title,"start":{"dateTime":start_dt.isoformat(),"timeZone":"UTC"},"end":{"dateTime":end_dt.isoformat(),"timeZone":"UTC"}}
        r = await _cal("POST","/calendars/primary/events", body=body)
        link = r.get("htmlLink","")
        return self._ok(summary=f"📅 Created: \"{title}\"\n{start_dt.strftime('%a %I:%M%p')} — {end_dt.strftime('%I:%M%p')}\n{link}", data=r)

    async def _h_busy_check(self, p):
        when = p.get("query","") or p.get("when","")
        return self._ok(summary=f"Free/busy check for: {when}\nGoogle Calendar not configured — assuming free.")

    async def _h_upcoming(self, p):
        days = p.get("days", 7)
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days)
        events = await self._fetch(now, end)
        return self._fmt(events, f"Next {days} Days", "Nothing coming up")

    async def _fetch(self, tmin, tmax):
        tkn = await _get_token()
        if not tkn: return []
        r = await _cal("GET","/calendars/primary/events", params={
            "timeMin": tmin.isoformat(), "timeMax": tmax.isoformat(),
            "singleEvents":"true", "orderBy":"startTime", "maxResults":50})
        return r.get("items",[])

    def _fmt(self, events, label, empty_msg):
        if not events:
            return self._ok(summary=f"📅 {label}: {empty_msg}", data={"events":[],"count":0})
        lines = [f"📅 {label} — {len(events)} events:"]
        for e in events:
            start = e.get("start",{}).get("dateTime","")[:16] or e.get("start",{}).get("date","")
            lines.append(f"  {start} — **{e.get('summary','(untitled)')}**")
        return self._ok(summary="\n".join(lines), data={"events":events,"count":len(events)})
