"""
Email Agent — checks inbox, reads threads, drafts replies via Gmail API.

Uses Gmail REST API with OAuth2 refresh token.
Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN in env.
Get these from https://console.cloud.google.com/apis/credentials

To get a refresh token, run: python -m agents.gmail_auth
"""
from __future__ import annotations

import base64
import logging
import os
from email.mime.text import MIMEText
from typing import Any

import httpx

from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.email")

GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Cache the access token
_access_token: str | None = None
_token_expiry: float = 0


async def _get_access_token() -> str:
    """Get a fresh Gmail access token using the refresh token."""
    global _access_token, _token_expiry
    import time as _time

    if _access_token and _time.time() < _token_expiry - 60:
        return _access_token

    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN", "")

    if not all([client_id, client_secret, refresh_token]):
        return ""

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
        if resp.status_code != 200:
            logger.warning("Gmail token refresh failed: %s", resp.text[:200])
            return ""

        data = resp.json()
        _access_token = data.get("access_token", "")
        _token_expiry = _time.time() + data.get("expires_in", 3600)
        return _access_token


async def _gmail_request(method: str, path: str, params: dict | None = None, json_body: dict | None = None) -> dict[str, Any]:
    """Make an authenticated Gmail API request."""
    token = await _get_access_token()
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
    name = "Email Agent"
    description = "Checks Gmail inbox, reads threads, drafts replies"

    def get_capabilities(self) -> dict[str, str]:
        return {
            "check_inbox": "Summarize recent Gmail emails in your inbox",
            "triage_inbox": "Categorize inbox emails by urgency and type (urgent, newsletter, personal, spam)",
            "read_thread": "Read a specific email thread by Gmail thread_id",
            "summarize_thread": "AI-powered summary of an entire email thread",
            "draft_reply": "AI-draft a reply to an email and save as Gmail draft",
            "search_emails": "Search Gmail by keyword, sender, subject, or date range",
            "send_draft": "Send a Gmail draft (requires approval)",
        }

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_handle_{action}", None)
        if not handler:
            return self._fail(f"Unknown action: {action}")
        return await handler(params)

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    async def _handle_check_inbox(self, params: dict[str, Any]) -> dict[str, Any]:
        limit = params.get("limit", 10)
        query = params.get("query", "in:inbox")

        # List message IDs
        resp = await _gmail_request("GET", f"/users/me/messages", params={"q": query, "maxResults": min(limit, 50)})
        messages = resp.get("messages", [])

        if not messages:
            return self._ok(
                summary="Inbox is empty or Gmail not configured. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN.",
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

        # AI draft
        draft_body = await self._ai_draft_reply(original_from, original_subject, original_body, tone, instructions)

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

        # AI categorization
        email_list = "\n".join(f"- {e['from'][:40]} | {e['subject'][:60]}" for e in emails[:15])
        try:
            import litellm
            prompt = f"""Categorize these {len(emails)} emails. Return JSON with categories:
- "urgent": needs immediate attention
- "important": should read today
- "newsletter": subscriptions and updates
- "promotional": marketing and ads
- "personal": from real people
- "spam_likely": looks like spam

Emails:
{email_list}

Return: {{"categories": {{"urgent": [list of indices], "important": [...], "newsletter": [...], "promotional": [...], "personal": [...], "spam_likely": [...]}}, "summary": "one-line summary"}}"""

            response = litellm.completion(
                model=os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=800,
            )
            text = response.choices[0].message.content.strip()
            import json as _json
            start = text.index("{")
            end = text.rindex("}") + 1
            cat_data = _json.loads(text[start:end])
        except Exception:
            cat_data = {"categories": {"all": list(range(len(emails)))}, "summary": f"{len(emails)} emails in inbox"}

        # Build readable summary
        cats = cat_data.get("categories", {})
        summary = f"📊 Inbox triage — {len(emails)} emails:\n"
        for cat, indices in cats.items():
            if indices:
                count = len(indices) if isinstance(indices, list) else 1
                summary += f"  {cat}: {count}\n"
        summary += f"\n{cat_data.get('summary', '')}"

        return self._ok(summary=summary, data={"emails": emails, "categories": cats, "count": len(emails)})

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

    async def _ai_draft_reply(self, sender: str, subject: str, body: str, tone: str, instructions: str) -> str:
        try:
            import litellm

            prompt = f"""Draft a {tone} email reply.

Original from: {sender}
Subject: {subject}
Body:
{body[:1500]}

{f'Additional instructions: {instructions}' if instructions else ''}

Write ONLY the reply body. No subject line. No AI disclaimers. Keep it concise and human."""
            response = litellm.completion(
                model=os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=1024,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.warning("AI draft failed: %s", exc)
            return f"[AI drafting unavailable: {exc}]\n\nOriginal from: {sender}\nSubject: {subject}"
