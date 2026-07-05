"""
Orchestrator Agent — the intelligent layer.

Instead of manually routing to specific agent actions, this agent:
1. Takes a natural language goal ("find latest Python news and email me")
2. Uses litellm function calling to decide which tools to use
3. Loops: plan → execute tool → observe result → decide next step
4. Returns a natural language summary when done
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.orchestrator")

MAX_LOOP_STEPS = 10  # safety limit


class OrchestratorAgent(BaseAgent):
    """
    The intelligent agent that sits on top of all other agents.
    Uses LLM reasoning to decide which tools to call and in what order.
    """

    name = "Orchestrator"
    description = "Intelligent agent — understands natural language, decides which tools to use, executes multi-step plans"

    def __init__(self, agent_registry: dict[str, BaseAgent] | None = None):
        self._registry = agent_registry or {}

    def set_registry(self, registry: dict[str, BaseAgent]) -> None:
        self._registry = registry

    def get_capabilities(self) -> dict[str, str]:
        return {
            "solve": "Solve any task using natural language. The agent figures out the steps.",
            "chat": "Have a conversation — ask questions, get help, brainstorm.",
        }

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "solve":
            return await self._handle_solve(params)
        if action == "chat":
            return await self._handle_chat(params)
        return self._fail(f"Unknown action: {action}")

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    async def _handle_solve(self, params: dict[str, Any]) -> dict[str, Any]:
        """Solve a goal using tool-calling loop."""
        goal = params.get("goal", "") or params.get("query", "") or params.get("prompt", "")
        max_steps = params.get("max_steps", MAX_LOOP_STEPS)
        conversation_history = params.get("history", [])

        if not goal:
            return self._fail("goal is required — describe what you want in natural language")

        tools = self._build_tools()
        if not tools:
            return self._fail("No agent tools available. Register agents first.")

        try:
            result = await self._agent_loop(goal, tools, conversation_history, max_steps)
            return self._ok(summary=result["summary"], data=result)
        except Exception as exc:
            logger.exception("Orchestrator loop failed")
            return self._fail(f"Failed to complete task: {exc}")

    async def _handle_chat(self, params: dict[str, Any]) -> dict[str, Any]:
        """Simple chat without tool calling."""
        message = params.get("message", "") or params.get("query", "")
        if not message:
            return self._fail("message is required")

        try:
            import litellm

            response = litellm.completion(
                model=os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ],
                temperature=0.7,
                max_tokens=1000,
            )
            reply = response.choices[0].message.content.strip()
            return self._ok(summary=reply, data={"reply": reply})
        except Exception as exc:
            return self._fail(f"Chat unavailable: {exc}")

    # ------------------------------------------------------------------
    # The agent loop
    # ------------------------------------------------------------------

    async def _agent_loop(
        self,
        goal: str,
        tools: list[dict[str, Any]],
        history: list[dict[str, str]],
        max_steps: int,
    ) -> dict[str, Any]:
        """Run the tool-calling loop with the LLM."""
        import litellm

        model = os.environ.get("LLM_MODEL", "openai/gpt-4o-mini")

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": goal},
        ]

        # Add conversation history if provided
        for h in history[-6:]:  # last 6 turns
            messages.append(h)

        steps_taken = []
        tool_results = []

        for iteration in range(max_steps):
            try:
                response = litellm.completion(
                    model=model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.3,
                    max_tokens=1500,
                )
            except Exception as exc:
                logger.warning("LLM call failed at step %d: %s", iteration, exc)
                # If we have some results, return what we got
                if steps_taken:
                    break
                raise

            msg = response.choices[0].message

            # If LLM returns a final text response (no tool call)
            if msg.content and not msg.tool_calls:
                return {
                    "summary": msg.content,
                    "steps": steps_taken,
                    "tool_results": tool_results,
                    "iterations": iteration + 1,
                }

            # Process tool calls
            if msg.tool_calls:
                # Add assistant message with tool calls
                messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in msg.tool_calls
                    ],
                })

                for tc in msg.tool_calls:
                    tool_name = tc.function.name
                    try:
                        tool_args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = {}

                    logger.info("Step %d: calling %s(%s)", iteration + 1, tool_name,
                                str(tool_args)[:100])

                    # Execute the tool
                    result = await self._execute_tool(tool_name, tool_args)
                    steps_taken.append({"tool": tool_name, "args": tool_args, "result_preview": str(result)[:200]})
                    tool_results.append({"tool": tool_name, "result": result})

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result)[:4000],  # Cap result size
                    })

        # If we hit max steps, ask LLM to summarize
        try:
            messages.append({
                "role": "user",
                "content": "You've reached the maximum steps. Summarize what you've found so far in a clear, helpful response.",
            })
            final = litellm.completion(
                model=model,
                messages=messages,
                temperature=0.3,
                max_tokens=1000,
            )
            summary = final.choices[0].message.content.strip()
        except Exception:
            summary = f"Completed {len(steps_taken)} steps. Results are in the data payload."

        return {
            "summary": summary,
            "steps": steps_taken,
            "tool_results": tool_results,
            "iterations": len(steps_taken),
            "note": "max steps reached",
        }

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def _execute_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool by routing to the right agent."""
        # Tool names are formatted as "agent__action"
        # e.g., "research__search", "email__check_inbox"

        if "__" in tool_name:
            agent_name, action = tool_name.split("__", 1)
        else:
            # Try to find which agent has this action
            agent_name = None
            for aname, agent in self._registry.items():
                if action_name := tool_name in agent.get_capabilities():
                    agent_name = aname
                    action = tool_name
                    break
            if not agent_name:
                return {"error": f"No agent found for tool: {tool_name}"}

        agent = self._registry.get(agent_name)
        if not agent:
            return {"error": f"Agent '{agent_name}' not found"}

        try:
            result = await agent.execute(action=action, params=args)
            return result
        except Exception as exc:
            return {"error": str(exc), "agent": agent_name, "action": action}

    # ------------------------------------------------------------------
    # Tool definitions
    # ------------------------------------------------------------------

    def _build_tools(self) -> list[dict[str, Any]]:
        """Build OpenAI-compatible tool definitions from all registered agents."""
        tools = []
        for agent_name, agent in self._registry.items():
            # Skip self to avoid recursion
            if agent_name == "orchestrator":
                continue
            for action, description in agent.get_capabilities().items():
                tool_name = f"{agent_name}__{action}"
                params = self._infer_params(agent_name, action, description)
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": f"[{agent_name}] {description}",
                        "parameters": {
                            "type": "object",
                            "properties": params,
                            "required": list(params.keys()) if params else [],
                        },
                    },
                })
        return tools

    def _infer_params(self, agent_name: str, action: str, description: str) -> dict[str, Any]:
        """Infer parameter schema for a tool based on agent and action name."""
        # Common patterns
        if action in ("search", "deep_research", "compare", "check_inbox", "search_emails",
                       "create_doc", "create_spreadsheet", "create_slides", "write_blog_post",
                       "format_report", "analyze_code", "suggest_fix", "explain_code", "optimize",
                       "summarize_url"):
            return {
                "query": {
                    "type": "string",
                    "description": "The search query, topic, code, or URL to process",
                }
            }
        if action in ("read_thread", "draft_reply"):
            return {
                "thread_id": {
                    "type": "string",
                    "description": "The email thread ID",
                }
            }
        if action == "generate_email_template":
            return {
                "scenario": {
                    "type": "string",
                    "description": "The email scenario (e.g., follow-up, introduction, thank-you)",
                }
            }
        if action == "send_draft":
            return {
                "draft_id": {
                    "type": "string",
                    "description": "The draft ID to send",
                }
            }
        if action == "review_pr":
            return {
                "diff": {
                    "type": "string",
                    "description": "The git diff or code changes to review",
                }
            }
        if action == "run_verifiers":
            return {
                "project": {
                    "type": "string",
                    "description": "Project path to run verifiers on",
                }
            }
        return {}


_SYSTEM_PROMPT = """You are an intelligent AI assistant with access to real-world tools.

You have tools for:
- research__search: Real web search via DuckDuckGo
- research__deep_research: Multi-step research with source synthesis
- research__summarize_url: Fetch and summarize any URL
- email__check_inbox: Check Gmail inbox
- email__read_thread: Read an email thread
- email__draft_reply: AI-draft a reply and save as draft
- email__search_emails: Search Gmail
- content__write_blog_post: Generate a blog post
- content__create_doc: Generate a document
- content__format_report: Generate a formatted report
- fixit__analyze_code: Analyze code for bugs
- fixit__explain_code: Explain what code does
- fixit__suggest_fix: Suggest a fix for an error

RULES:
1. Understand the user's goal in natural language
2. Call the right tools in the right order
3. Use results from one tool as input to the next
4. If a tool fails, try an alternative approach
5. When done, summarize what you found in clear, helpful language
6. If the user just wants to chat, respond directly without tools
7. Never make up information — only report what tools actually returned
8. Be concise. The user is on a phone."""
