"""
Email Agent — checks inbox, reads threads, drafts replies via Gmail API.

Supports MULTIPLE Gmail accounts via GOOGLE_ACCOUNTS env var:
  GOOGLE_ACCOUNTS='[{"email":"you@gmail.com","client_id":"...","client_secret":"...","refresh_token":"..."}]'

Or single account (backward compat):
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN
"""
from __future__ import annotations

import base64
import json as _json
import logging
import os
from email.mime.text import MIMEText
from typing import Any

import httpx

from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.email")

GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Cache: { "email@domain.com": {"access_token": "...", "expiry": 1234567890} }
_token_cache: dict[str, dict] = {}


def _load_accounts() -> list[dict]:
    """Load Gmail account configs from env."""
    accounts_json = os.environ.get("GOOGLE_ACCOUNTS", "")
    if accounts_json:
        try:
            return _json.loads(accounts_json)
        except Exception:
            pass

    # Fallback: single account from old env vars
    cid = os.environ.get("GOOGLE_CLIENT_ID", "")
    csec = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    rtok = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
    if all([cid, csec, rtok]):
        return [{"email": "default", "client_id": cid, "client_secret": csec, "refresh_token": rtok}]
    return []


async def _get_access_token(account_email: str = "") -> str:
    """Get a fresh access token for a specific account."""
    import time as _time

    accounts = _load_accounts()
    if not accounts:
        return ""

    # Find the right account
    account = None
    for a in accounts:
        if a["email"] == account_email or (not account_email and a["email"] == "default"):
            account = a
            break
    if not account:
        account = accounts[0]  # first available

    email_key = account.get("email", "default")

    # Check cache
    cached = _token_cache.get(email_key)
    if cached and _time.time() < cached.get("expiry", 0) - 60:
        return cached["access_token"]

    # Refresh
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data={
            "client_id": account["client_id"],
            "client_secret": account["client_secret"],
            "refresh_token": account["refresh_token"],
            "grant_type": "refresh_token",
        })
        if resp.status_code != 200:
            logger.warning("Gmail token refresh failed for %s: %s", email_key, resp.text[:200])
            return ""

        data = resp.json()
        _token_cache[email_key] = {
            "access_token": data.get("access_token", ""),
            "expiry": _time.time() + data.get("expires_in", 3600),
        }
        return data.get("access_token", "")


async def _gmail_request(method: str, path: str, params: dict | None = None, json_body: dict | None = None, account: str = "") -> dict[str, Any]:
    """Make an authenticated Gmail API request for a specific account."""
    token = await _get_access_token(account)
    if not token:
        return {}

    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GMAIL_API}{path}"

    async with httpx.AsyncClient(timeout=20) as client:
        if method == "GET":
            resp = await client.get(url, headers=headers, params=params)
        elif method == "POST":
            resp = await client.post(url, headers=headers, json=json_body)
        else:
            return {}

        if resp.status_code not in (200, 201):
            logger.warning("Gmail API %s %s → %d: %s", method, path, resp.status_code, resp.text[:200])
            return {}
        return resp.json() if resp.text else {}


def _decode_email_part(part: dict) -> str:
    """Decode a base64-encoded email part."""
    data = part.get("body", {}).get("data", "")
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
    except Exception:
        return "[binary content]"


class EmailAgent(BaseAgent):
    name = "Inbox"
    codename = "inbox"
    emoji = "📬"
    color = "#3b82f6"
    personality = "Your digital gatekeeper. Guards your attention, surfaces what matters, drafts replies that sound like you."
    description = "Gmail inbox management, smart triage, thread summaries, AI-drafted replies"

    def get_capabilities(self) -> dict[str, str]:
        return {
            "check_inbox": "📬 Legion's Watch — summarize recent Gmail emails in your inbox",
            "triage_inbox": "⚔️ Abaddon's Judgment — categorize inbox by urgency and type",
            "read_thread": "📖 Mammon's Ledger — read a specific email thread",
            "summarize_thread": "💀 Azrael's Summary — AI-powered summary of an entire thread",
            "draft_reply": "🩸 Belial's Tongue — AI-draft a reply and save as Gmail draft",
            "search_emails": "🔎 Asmodeus' Gaze — search Gmail by keyword, sender, date range",
            "send_draft": "📨 Leviathan's Missive — send a Gmail draft (requires approval)",
            "list_accounts": "📋 Beelzebub's Registry — list configured Gmail accounts",
            "bulk_archive": "🗑️ Moloch's Fire — archive or delete emails by query",
            "email_analytics": "📊 Lucifer's Census — analyze email patterns and top senders",
        }

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_handle_{action}", None)
        if not handler:
            return self._fail(f"Unknown action: {action}")
        return await handler(params)

    def _acct(self, params: dict) -> str:
        """Extract account email from params."""
        return params.get("account", "")

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    async def _handle_check_inbox(self, params: dict[str, Any]) -> dict[str, Any]:
        limit = params.get("limit", 10)
        query = params.get("query", "in:inbox")
        acct = self._acct(params)

        # List message IDs
        resp = await _gmail_request("GET", f"/users/me/messages", params={"q": query, "maxResults": min(limit, 50)}, account=acct)
        messages = resp.get("messages", [])

        if not messages:
            return self._ok(
                summary="Inbox is empty or Gmail not configured. Set GOOGLE_ACCOUNTS or GOOGLE_REFRESH_TOKEN on Railway.",
                data={"emails": [], "count": 0},
            )

        # Fetch details for each
        emails = []
        for msg in messages[:limit]:
            detail = await _gmail_request("GET", f"/users/me/messages/{msg['id']}", params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]})
            if not detail:
                continue

            headers = {}
            for h in detail.get("payload", {}).get("headers", []):
                headers[h["name"].lower()] = h["value"]

            emails.append({
                "id": detail["id"],
                "thread_id": detail.get("threadId", ""),
                "from": headers.get("from", "?"),
                "subject": headers.get("subject", "(no subject)"),
                "date": headers.get("date", ""),
                "snippet": detail.get("snippet", "")[:200],
            })

        lines = []
        for i, em in enumerate(emails, 1):
            sender = em["from"].split("<")[0].strip()[:40]
            subject = em["subject"][:60]
            lines.append(f"{i}. **{sender}**: {subject}")

        summary = f"Inbox has {len(emails)} emails:\n\n" + "\n".join(lines)
        return self._ok(summary=summary, data={"emails": emails, "count": len(emails)})

    async def _handle_read_thread(self, params: dict[str, Any]) -> dict[str, Any]:
        thread_id = params.get("thread_id", "")
        if not thread_id:
            return self._fail("thread_id is required")

        resp = await _gmail_request("GET", f"/users/me/threads/{thread_id}", params={"format": "full"})
        if not resp:
            return self._fail(f"Thread {thread_id} not found or Gmail not configured")

        messages = []
        for msg in resp.get("messages", []):
            headers = {}
            for h in msg.get("payload", {}).get("headers", []):
                headers[h["name"].lower()] = h["value"]

            # Get body text
            body_text = msg.get("snippet", "")
            parts = msg.get("payload", {}).get("parts", [])
            for part in parts:
                if part.get("mimeType") == "text/plain":
                    body_text = _decode_email_part(part)
                    break

            messages.append({
                "id": msg["id"],
                "from": headers.get("from", "?"),
                "subject": headers.get("subject", ""),
                "date": headers.get("date", ""),
                "body": body_text[:3000],
            })

        subject = messages[0]["subject"] if messages else "(no subject)"
        participants = list(set(m["from"] for m in messages))

        lines = []
        for m in messages:
            sender = m["from"].split("<")[0].strip()[:30]
            body_preview = m["body"][:100].replace("\n", " ")
            lines.append(f"  [{m['date'][:16]}] **{sender}**: {body_preview}")

        summary = f"Thread: {subject}\n{len(messages)} messages, {len(participants)} participants\n\n" + "\n\n".join(lines)
        return self._ok(summary=summary, data={"thread_id": thread_id, "messages": messages, "subject": subject})

    async def _handle_draft_reply(self, params: dict[str, Any]) -> dict[str, Any]:
        thread_id = params.get("thread_id", "")
        message_id = params.get("message_id", "")
        tone = params.get("tone", "professional")
        instructions = params.get("instructions", "")

        if not thread_id and not message_id:
            return self._fail("thread_id or message_id is required")

        # Fetch the original email
        if message_id:
            resp = await _gmail_request("GET", f"/users/me/messages/{message_id}", params={"format": "full"})
        else:
            thread_resp = await _gmail_request("GET", f"/users/me/threads/{thread_id}", params={"format": "full"})
            messages = thread_resp.get("messages", [])
            resp = messages[-1] if messages else {}
            message_id = resp.get("id", "")

        if not resp:
            return self._fail("Could not fetch the original email")

        # Extract details
        headers = {}
        for h in resp.get("payload", {}).get("headers", []):
            headers[h["name"].lower()] = h["value"]

        original_subject = headers.get("subject", "(no subject)")
        original_from = headers.get("from", "?")
        original_body = resp.get("snippet", "")

        # Fetch full thread for context
        thread_context = ""
        if resp.get("threadId"):
            thread_resp = await _gmail_request("GET", f"/users/me/threads/{resp['threadId']}", params={"format": "full"})
            if thread_resp:
                thread_msgs = thread_resp.get("messages", [])
                thread_context = "\n---\n".join(
                    f"From: {next((h['value'] for h in m.get('payload',{}).get('headers',[]) if h['name'].lower()=='from'), '?')}\n{m.get('snippet','')[:300]}"
                    for m in thread_msgs[-5:]  # last 5 messages for context
                )

        # AI draft with full context
        draft_body = await self._ai_draft_reply(original_from, original_subject, original_body, tone, instructions, thread_context)

        reply_subject = original_subject if original_subject.startswith("Re:") else f"Re: {original_subject}"

        # Create draft in Gmail
        draft_result = await self._create_gmail_draft(
            to=headers.get("from", ""),
            subject=reply_subject,
            body=draft_body,
            thread_id=resp.get("threadId", ""),
            in_reply_to=message_id,
        )

        if draft_result:
            return self._ok(
                summary=f"Gmail draft saved: \"{reply_subject}\"\nReply to: {original_from}\n\n---\n{draft_body[:500]}",
                data={"draft": draft_result, "action": "draft_saved"},
            )

        return self._ok(
            summary=f"AI-drafted reply to {original_from}:\n\nSubject: {reply_subject}\n\n{draft_body[:600]}",
            data={"subject": reply_subject, "body": draft_body, "to": original_from, "mode": "demo"},
        )

    async def _handle_search_emails(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "")
        if not query:
            return self._fail("query is required")

        # Build Gmail search query
        gmail_query = query
        if params.get("from"):
            gmail_query += f" from:{params['from']}"
        if params.get("subject"):
            gmail_query += f" subject:{params['subject']}"

        resp = await _gmail_request("GET", "/users/me/messages", params={"q": gmail_query, "maxResults": 20})
        messages = resp.get("messages", [])

        if not messages:
            return self._ok(summary=f"No emails found matching '{query}'", data={"emails": [], "count": 0})

        # Fetch headers for each
        emails = []
        for msg in messages[:10]:
            detail = await _gmail_request("GET", f"/users/me/messages/{msg['id']}", params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]})
            if detail:
                headers = {}
                for h in detail.get("payload", {}).get("headers", []):
                    headers[h["name"].lower()] = h["value"]
                emails.append({
                    "id": detail["id"],
                    "thread_id": detail.get("threadId", ""),
                    "from": headers.get("from", "?"),
                    "subject": headers.get("subject", ""),
                    "date": headers.get("date", ""),
                    "snippet": detail.get("snippet", "")[:150],
                })

        lines = [f"{i+1}. **{e['from'].split('<')[0].strip()[:30]}**: {e['subject'][:60]}" for i, e in enumerate(emails)]
        summary = f"Found {len(emails)} emails matching '{query}':\n\n" + "\n".join(lines)
        return self._ok(summary=summary, data={"emails": emails, "count": len(emails)})

    async def _handle_triage_inbox(self, params: dict[str, Any]) -> dict[str, Any]:
        """Categorize inbox emails by urgency and type."""
        limit = params.get("limit", 20)

        resp = await _gmail_request("GET", "/users/me/messages", params={"q": "in:inbox", "maxResults": min(limit, 50)})
        messages = resp.get("messages", [])

        if not messages:
            return self._ok(summary="Inbox empty or Gmail not configured.", data={"categories": {}, "count": 0})

        # Fetch subjects and senders
        emails = []
        for msg in messages[:limit]:
            detail = await _gmail_request("GET", f"/users/me/messages/{msg['id']}", params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]})
            if detail:
                headers = {}
                for h in detail.get("payload", {}).get("headers", []):
                    headers[h["name"].lower()] = h["value"]
                emails.append({
                    "id": detail["id"], "from": headers.get("from", ""),
                    "subject": headers.get("subject", ""), "date": headers.get("date", ""),
                    "snippet": detail.get("snippet", "")[:100],
                })

        # AI categorization — now with full body context
        email_list = "\n".join(f"{i}. {e['from'][:50]} | {e['subject'][:80]} | {e['snippet'][:200]}" for i, e in enumerate(emails[:15]))
        try:
            import litellm
            prompt = f"""You are Inbox, an intelligent email gatekeeper. Analyze these {len(emails)} emails and categorize them.

For each category, list the email indices that match. Also provide actionable advice.

Emails:
{email_list}

Return JSON:
{{
  "categories": {{
    "urgent": [indices of emails needing immediate response],
    "important": [indices of emails to read today],
    "newsletter": [indices of subscriptions/updates],
    "promotional": [indices of marketing/ads],
    "personal": [indices from real people],
    "spam_likely": [indices that look like spam]
  }},
  "summary": "one-line overview of what's in the inbox",
  "action_items": ["specific thing you should do about email X", "another action"],
  "top_3_emails": ["brief description of the most important email", ...]
}}"""

            response = litellm.completion(
                model=os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
                messages=[{"role": "system", "content": "You are Inbox, a sharp email assistant. Be concise and actionable."},
                          {"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=1000,
            )
            text = response.choices[0].message.content.strip()
            import json as _json
            start = text.index("{")
            end = text.rindex("}") + 1
            cat_data = _json.loads(text[start:end])
        except Exception:
            cat_data = {"categories": {}, "summary": f"{len(emails)} emails", "action_items": [], "top_3_emails": []}

        cats = cat_data.get("categories", {})
        actions = cat_data.get("action_items", [])
        top = cat_data.get("top_3_emails", [])

        summary = f"📊 Inbox — {len(emails)} emails\n"
        for cat, indices in cats.items():
            if indices:
                summary += f"  {cat}: {len(indices)}\n"
        if top:
            summary += "\n📌 Top emails:\n" + "\n".join(f"  • {t}" for t in top[:3])
        if actions:
            summary += "\n\n✅ Suggested actions:\n" + "\n".join(f"  • {a}" for a in actions[:3])

        return self._ok(summary=summary, data={"emails": emails, "categories": cats, "actions": actions, "top": top})

    async def _handle_summarize_thread(self, params: dict[str, Any]) -> dict[str, Any]:
        """AI-powered summary of an email thread."""
        thread_id = params.get("thread_id", "")
        if not thread_id:
            return self._fail("thread_id is required")

        resp = await _gmail_request("GET", f"/users/me/threads/{thread_id}", params={"format": "full"})
        if not resp:
            return self._fail(f"Thread {thread_id} not found or Gmail not configured")

        messages = []
        for msg in resp.get("messages", []):
            headers = {}
            for h in msg.get("payload", {}).get("headers", []):
                headers[h["name"].lower()] = h["value"]
            messages.append({
                "from": headers.get("from", "?"),
                "date": headers.get("date", ""),
                "body": msg.get("snippet", "")[:500],
            })

        # AI summary
        thread_text = "\n\n".join(f"[{m['date'][:16]}] {m['from']}: {m['body']}" for m in messages)
        try:
            import litellm
            prompt = f"""Summarize this email thread in 3-5 bullet points. Include who said what and any decisions or action items.

Thread:
{thread_text[:3000]}

Format:
- Key topic: ...
- Main points: ...
- Decisions made: ...
- Action items: ...
- Next steps: ..."""

            response = litellm.completion(
                model=os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=600,
            )
            summary = response.choices[0].message.content.strip()
        except Exception:
            summary = f"Thread with {len(messages)} messages. First message from {messages[0]['from']}."

        return self._ok(summary=summary, data={"thread_id": thread_id, "message_count": len(messages), "participants": list(set(m['from'] for m in messages))})

    async def _handle_bulk_archive(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "category:promotional OR category:social")
        action_type = params.get("action", "archive")
        acct = self._acct(params)
        resp = await _gmail_request("GET","/users/me/messages",params={"q":query,"maxResults":50},account=acct)
        messages = resp.get("messages",[])
        if not messages:
            return self._ok(summary=f"No emails found matching: {query}",data={"count":0})
        count = len(messages)
        if action_type == "archive":
            ids = [m["id"] for m in messages[:50]]
            await _gmail_request("POST","/users/me/messages/batchModify",json_body={"ids":ids,"removeLabelIds":["INBOX"]},account=acct)
            return self._ok(summary=f"Archived {count} emails matching: {query}",data={"count":count,"query":query})
        elif action_type == "trash":
            ids = [m["id"] for m in messages[:50]]
            await _gmail_request("POST","/users/me/messages/batchModify",json_body={"ids":ids,"addLabelIds":["TRASH"],"removeLabelIds":["INBOX"]},account=acct)
            return self._ok(summary=f"Trashed {count} emails matching: {query}",data={"count":count,"query":query})
        return self._ok(summary=f"Found {count} emails. Use action=archive or action=trash.",data={"count":count})

    async def _handle_email_analytics(self, params: dict[str, Any]) -> dict[str, Any]:
        days = params.get("days",30)
        acct = self._acct(params)
        resp = await _gmail_request("GET","/users/me/messages",params={"q":f"newer_than:{days}d","maxResults":100},account=acct)
        messages = resp.get("messages",[])
        if not messages:
            return self._ok(summary="No emails to analyze.",data={})
        senders = {}
        for msg in messages[:50]:
            detail = await _gmail_request("GET",f"/users/me/messages/{msg['id']}",params={"format":"metadata","metadataHeaders":["From","Date"]},account=acct)
            if detail:
                headers = {}
                for h in detail.get("payload",{}).get("headers",[]):
                    headers[h["name"].lower()] = h["value"]
                sender = headers.get("from","?").split("<")[0].strip()
                senders[sender] = senders.get(sender,0) + 1
        top = sorted(senders.items(),key=lambda x:x[1],reverse=True)[:10]
        summary = f"📊 Email analytics (last {days} days, {len(messages)} emails)\n\nTop senders:\n"
        for name,count in top:
            bar = "█" * min(count,20)
            summary += f"  {name[:30]:<30} {count:>3} {bar}\n"
        summary += f"\nDaily average: ~{len(messages)//max(days,1)} emails"
        return self._ok(summary=summary,data={"senders":dict(top),"total":len(messages),"days":days})

    async def _handle_list_accounts(self, params: dict[str, Any]) -> dict[str, Any]:
        """List configured Gmail accounts."""
        accounts = _load_accounts()
        if not accounts:
            return self._ok(summary="No Gmail accounts configured.", data={"accounts": [], "count": 0})

        lines = [f"  {a.get('email', 'default')}" for a in accounts]
        return self._ok(
            summary=f"{len(accounts)} Gmail account(s) configured:\n" + "\n".join(lines),
            data={"accounts": [a.get("email", "default") for a in accounts], "count": len(accounts)},
        )

    async def _handle_send_draft(self, params: dict[str, Any]) -> dict[str, Any]:
        draft_id = params.get("draft_id", "")
        if not draft_id:
            return self._fail("draft_id is required")
        return self._approval_needed(
            summary=f"Send Gmail draft {draft_id}? This action requires confirmation.",
            data={"draft_id": draft_id, "action": "send"},
        )

    # ------------------------------------------------------------------
    # Gmail API helpers
    # ------------------------------------------------------------------

    async def _create_gmail_draft(self, to: str, subject: str, body: str, thread_id: str = "", in_reply_to: str = "") -> dict[str, Any] | None:
        """Create a draft in Gmail via the API."""
        token = await _get_access_token()
        if not token:
            return None

        # Build RFC 2822 message
        from email.mime.text import MIMEText
        from email.utils import formataddr
        import base64 as b64

        msg = MIMEText(body)
        msg["To"] = to
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        raw = b64.urlsafe_b64encode(msg.as_bytes()).decode()

        draft_body = {
            "message": {
                "raw": raw,
                "threadId": thread_id,
            }
        }

        result = await _gmail_request("POST", "/users/me/drafts", json_body=draft_body)
        if result:
            return {"id": result.get("id", ""), "message_id": result.get("message", {}).get("id", "")}
        return None

    # ------------------------------------------------------------------
    # AI drafting via litellm
    # ------------------------------------------------------------------

    async def _ai_draft_reply(self, sender: str, subject: str, body: str, tone: str, instructions: str, thread_context: str = "") -> str:
        try:
            import litellm

            prompt = f"""You are Inbox, writing a {tone} email reply on behalf of your user.

Original sender: {sender}
Subject: {subject}
Latest message:
{body[:1500]}

{f'Full thread context:\n{thread_context[:2000]}' if thread_context else ''}
{f'Special instructions: {instructions}' if instructions else ''}

Write the reply body. Rules:
- Match the tone and formality of the original
- Address all points raised in the latest message
- Reference thread context if helpful
- Be concise — people read email on phones
- No AI disclaimers or signatures
- Sound like a real human wrote it"""
            response = litellm.completion(
                model=os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
                messages=[{"role": "system", "content": "You are Inbox, a sharp email assistant. Your replies sound human, not robotic."},
                          {"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=1024,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.warning("AI draft failed: %s", exc)
            return f"[AI drafting unavailable: {exc}]\n\nOriginal from: {sender}\nSubject: {subject}"
