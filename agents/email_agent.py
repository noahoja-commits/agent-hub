"""
Email Agent — checks inbox, reads threads, drafts replies.

Uses Lark Mail OpenAPI for email operations and litellm for AI drafting.
Set LARK_APP_ID, LARK_APP_SECRET, and LARK_USER_ACCESS_TOKEN in env.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.email")

# Lark Mail API base
LARK_BASE = "https://open.larksuite.com/open-apis"

# Hard flag: never auto-send. Drafts only unless user explicitly approves.
DRAFTS_ONLY = True


def _lark_headers() -> dict[str, str]:
    """Build authorization headers for Lark OpenAPI."""
    token = os.environ.get("LARK_USER_ACCESS_TOKEN", "")
    if not token:
        # Fall back to tenant access token
        token = os.environ.get("LARK_TENANT_ACCESS_TOKEN", "")
    if not token:
        logger.warning("No Lark access token configured — email agent will run in demo mode")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


class EmailAgent(BaseAgent):
    name = "Email Agent"
    description = "Checks inbox, reads email threads, drafts replies via Lark Mail"

    def get_capabilities(self) -> dict[str, str]:
        return {
            "check_inbox": "Summarize recent emails in your inbox",
            "read_thread": "Read a specific email thread by thread_id",
            "draft_reply": "Draft a reply to an email (saves as draft, never auto-sends)",
            "search_emails": "Search emails by keyword or sender",
            "send_draft": "Send a previously drafted email (requires approval)",
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
        """Fetch recent inbox emails and return a summary."""
        limit = params.get("limit", 10)
        emails = await self._fetch_emails(folder="INBOX", page_size=min(limit, 50))

        if not emails:
            return self._ok(
                summary="Inbox is empty or unable to fetch emails.",
                data={"emails": [], "count": 0},
            )

        # Build a readable summary
        lines = []
        for i, em in enumerate(emails, 1):
            subject = em.get("subject", "(no subject)")[:80]
            sender = ", ".join(a.get("address_name", a.get("address", "?")) for a in em.get("from", []))[:50]
            received = em.get("received_at", "")[:16]
            lines.append(f"{i}. [{received}] **{sender}**: {subject}")

        summary = f"Inbox has {len(emails)} recent emails:\n\n" + "\n".join(lines)
        return self._ok(summary=summary, data={"emails": emails, "count": len(emails)})

    async def _handle_read_thread(self, params: dict[str, Any]) -> dict[str, Any]:
        """Read a full email thread."""
        thread_id = params.get("thread_id", "")
        if not thread_id:
            return self._fail("thread_id is required")

        messages = await self._fetch_thread(thread_id)

        if not messages:
            return self._fail(f"No messages found for thread {thread_id}")

        # Summarize the thread
        thread_summary = self._summarize_thread(messages)

        return self._ok(
            summary=f"Thread: {thread_summary['subject']}\n{len(messages)} messages",
            data={"thread_id": thread_id, "messages": messages, "summary": thread_summary},
        )

    async def _handle_draft_reply(self, params: dict[str, Any]) -> dict[str, Any]:
        """Draft a reply to an email. Saves as draft, does NOT send."""
        thread_id = params.get("thread_id", "")
        message_id = params.get("message_id", "")
        tone = params.get("tone", "professional")
        instructions = params.get("instructions", "")

        if not thread_id and not message_id:
            return self._fail("thread_id or message_id is required")

        # Fetch the email to reply to
        if message_id:
            original = await self._fetch_message(message_id)
        else:
            messages = await self._fetch_thread(thread_id)
            original = messages[-1] if messages else None

        if not original:
            return self._fail("Could not fetch the original email")

        # Use litellm to draft the reply
        draft_body = await self._ai_draft_reply(original, tone, instructions)
        subject = original.get("subject", "Re:")
        if not subject.startswith("Re:"):
            subject = f"Re: {subject}"

        # Save as draft via Lark API
        draft = await self._create_draft(
            subject=subject,
            body=draft_body,
            to=self._extract_reply_to(original),
            in_reply_to=original.get("message_id", ""),
        )

        if draft:
            if DRAFTS_ONLY:
                return self._ok(
                    summary=f"Draft saved: \"{subject}\"\nReply to: {self._extract_sender_names(original)}\n\n---\n{draft_body[:500]}{'...' if len(draft_body) > 500 else ''}",
                    data={"draft": draft, "action": "draft_saved"},
                )
            else:
                # Send path — must go through approval
                return self._approval_needed(
                    summary=f"Draft ready to send: \"{subject}\"",
                    data={"draft": draft, "action": "ready_to_send"},
                )

        # Demo mode — return the AI draft without saving
        sender = self._extract_sender_names(original)
        return self._ok(
            summary=f"AI-drafted reply to {sender}:\n\nSubject: {subject}\n\n{draft_body[:800]}{'...' if len(draft_body) > 800 else ''}",
            data={
                "subject": subject,
                "body": draft_body,
                "to": self._extract_reply_to(original),
                "mode": "demo",
            },
        )

    async def _handle_search_emails(self, params: dict[str, Any]) -> dict[str, Any]:
        """Search emails by query."""
        query = params.get("query", "")
        if not query:
            return self._fail("query is required")

        emails = await self._search_emails(query)

        if not emails:
            return self._ok(summary=f"No emails found matching '{query}'", data={"emails": [], "count": 0})

        lines = []
        for i, em in enumerate(emails[:10], 1):
            subject = em.get("subject", "(no subject)")[:80]
            sender = ", ".join(a.get("address_name", a.get("address", "?")) for a in em.get("from", []))[:50]
            lines.append(f"{i}. **{sender}**: {subject}")

        summary = f"Found {len(emails)} emails matching '{query}':\n\n" + "\n".join(lines)
        return self._ok(summary=summary, data={"emails": emails, "count": len(emails)})

    async def _handle_send_draft(self, params: dict[str, Any]) -> dict[str, Any]:
        """Send a draft — requires explicit approval."""
        draft_id = params.get("draft_id", "")
        if not draft_id:
            return self._fail("draft_id is required")
        return self._approval_needed(
            summary=f"Send draft {draft_id}? This action requires confirmation.",
            data={"draft_id": draft_id, "action": "send"},
        )

    # ------------------------------------------------------------------
    # Lark Mail API helpers
    # ------------------------------------------------------------------

    async def _fetch_emails(self, folder: str = "INBOX", page_size: int = 20) -> list[dict[str, Any]]:
        """Fetch email list from a folder."""
        headers = _lark_headers()
        if not headers["Authorization"].strip("Bearer "):
            return []  # Demo mode — no credentials

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{LARK_BASE}/mail/v1/user_mailboxes/me/messages",
                    headers=headers,
                    params={"page_size": page_size},
                )
                if resp.status_code != 200:
                    logger.warning("Lark API returned %d: %s", resp.status_code, resp.text[:200])
                    return []
                data = resp.json()
                items = data.get("data", {}).get("items", [])
                # Fetch details for each message
                return [await self._fetch_message(m["message_id"]) for m in items[:page_size] if m.get("message_id")]
        except Exception as exc:
            logger.warning("Failed to fetch emails: %s", exc)
            return []

    async def _fetch_message(self, message_id: str) -> dict[str, Any] | None:
        """Fetch a single email message by ID."""
        headers = _lark_headers()
        if not headers["Authorization"].strip("Bearer "):
            return None
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{LARK_BASE}/mail/v1/user_mailboxes/me/messages/{message_id}",
                    headers=headers,
                )
                if resp.status_code != 200:
                    return None
                return resp.json().get("data", {}).get("items", [{}])[0] if resp.json().get("data", {}).get("items") else {}
        except Exception as exc:
            logger.warning("Failed to fetch message %s: %s", message_id, exc)
            return None

    async def _fetch_thread(self, thread_id: str) -> list[dict[str, Any]]:
        """Fetch all messages in a thread."""
        headers = _lark_headers()
        if not headers["Authorization"].strip("Bearer "):
            return []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{LARK_BASE}/mail/v1/user_mailboxes/me/threads/{thread_id}/messages",
                    headers=headers,
                )
                if resp.status_code != 200:
                    return []
                return resp.json().get("data", {}).get("items", [])
        except Exception as exc:
            logger.warning("Failed to fetch thread %s: %s", thread_id, exc)
            return []

    async def _search_emails(self, query: str) -> list[dict[str, Any]]:
        """Search emails by query string."""
        headers = _lark_headers()
        if not headers["Authorization"].strip("Bearer "):
            return []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{LARK_BASE}/mail/v1/user_mailboxes/me/messages",
                    headers=headers,
                    params={"query": query, "page_size": 20},
                )
                if resp.status_code != 200:
                    return []
                data = resp.json()
                return data.get("data", {}).get("items", [])
        except Exception as exc:
            logger.warning("Failed to search emails: %s", exc)
            return []

    async def _create_draft(
        self, subject: str, body: str, to: list[dict[str, str]], in_reply_to: str = ""
    ) -> dict[str, Any] | None:
        """Create a draft email via Lark API."""
        headers = _lark_headers()
        if not headers["Authorization"].strip("Bearer "):
            return None

        payload = {
            "subject": subject,
            "body": {"content": body, "content_type": "text/html"},
            "to": to,
        }
        if in_reply_to:
            payload["in_reply_to"] = in_reply_to

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{LARK_BASE}/mail/v1/user_mailboxes/me/drafts",
                    headers=headers,
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    return resp.json().get("data", {})
                logger.warning("Draft creation failed: %d — %s", resp.status_code, resp.text[:200])
                return None
        except Exception as exc:
            logger.warning("Failed to create draft: %s", exc)
            return None

    # ------------------------------------------------------------------
    # AI drafting via litellm
    # ------------------------------------------------------------------

    async def _ai_draft_reply(
        self, original: dict[str, Any], tone: str, instructions: str
    ) -> str:
        """Use litellm to draft a reply."""
        try:
            import litellm

            subject = original.get("subject", "(no subject)")
            body_text = original.get("body", {}).get("content", "")[:2000]
            sender = self._extract_sender_names(original)

            prompt = f"""Draft a {tone} email reply.

Original email from {sender}:
Subject: {subject}
Body:
{body_text}

{f'Additional instructions: {instructions}' if instructions else ''}

Write ONLY the reply body (no subject line, no signatures explaining you're AI).
Keep it concise. Match the tone and formality of the original."""

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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_sender_names(self, email: dict[str, Any]) -> str:
        """Extract sender display names from an email object."""
        senders = email.get("from", [])
        names = [a.get("address_name", a.get("address", "?")) for a in senders]
        return ", ".join(names)

    def _extract_reply_to(self, email: dict[str, Any]) -> list[dict[str, str]]:
        """Extract reply-to addresses from an email."""
        senders = email.get("from", [])
        return [{"address": a.get("address", ""), "name": a.get("address_name", "")} for a in senders]

    def _summarize_thread(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Build a readable thread summary."""
        if not messages:
            return {"subject": "(empty)", "participants": [], "message_count": 0}

        subject = messages[0].get("subject", "(no subject)")
        participants: set[str] = set()
        for m in messages:
            for a in m.get("from", []):
                participants.add(a.get("address_name", a.get("address", "?")))

        return {
            "subject": subject,
            "participants": list(participants),
            "message_count": len(messages),
        }
