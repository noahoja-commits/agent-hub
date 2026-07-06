"""
Base agent class and shared utilities for Agent Hub agents.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger("agent-hub.agents")


class BaseAgent(ABC):
    """Abstract base for all Agent Hub agents.

    Each agent has:
    - A name and description for the registry
    - A capabilities dict mapping action names → descriptions
    - An execute() method that takes (action, params) → returns result dict
    """

    name: str
    description: str
    emoji: str = "🤖"
    color: str = "#3b82f6"
    personality: str = ""
    codename: str = ""

    @abstractmethod
    def get_capabilities(self) -> dict[str, str]:
        """Return {action_name: description} for this agent."""

    @abstractmethod
    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a named action with parameters. Returns a result dict.

        Result dict convention:
            {"status": "completed|awaiting_approval|failed",
             "summary": "...",
             "data": {...}}
        """

    def _ok(self, summary: str, data: Any = None) -> dict[str, Any]:
        return {"status": "completed", "summary": summary, "data": data}

    def _approval_needed(self, summary: str, data: Any = None) -> dict[str, Any]:
        return {"status": "awaiting_approval", "summary": summary, "data": data}

    def _fail(self, summary: str, data: Any = None) -> dict[str, Any]:
        return {"status": "failed", "summary": summary, "data": data}
