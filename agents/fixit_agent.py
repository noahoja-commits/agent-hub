"""
Fixit Agent — code analysis, bug detection, verifier runs.

Uses litellm for code reasoning. Integrates with local PC agent for
running actual verifiers and reading files.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.fixit")


class FixitAgent(BaseAgent):
    name = "Fixit Agent"
    description = "Analyzes code, finds bugs, suggests fixes, runs verifiers, reviews PRs"

    def get_capabilities(self) -> dict[str, str]:
        return {
            "analyze_code": "Analyze code for bugs, anti-patterns, and improvements",
            "suggest_fix": "Suggest a fix for a specific error or bug",
            "review_pr": "Review a pull request or code diff",
            "run_verifiers": "Run project verifiers (tests, lints) — requires local PC agent",
            "explain_code": "Explain what a piece of code does",
            "optimize": "Suggest performance or structure optimizations",
        }

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_handle_{action}", None)
        if not handler:
            return self._fail(f"Unknown action: {action}")
        return await handler(params)

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    async def _handle_analyze_code(self, params: dict[str, Any]) -> dict[str, Any]:
        """Analyze code for issues."""
        code = params.get("code", "")
        language = params.get("language", "")
        focus = params.get("focus", "bugs, style, performance")

        if not code:
            return self._fail("code is required — provide the code snippet to analyze")

        analysis = await self._ai_analyze(code, language, focus)
        return self._ok(
            summary=analysis,
            data={"language": language, "focus": focus, "code_length": len(code)},
        )

    async def _handle_suggest_fix(self, params: dict[str, Any]) -> dict[str, Any]:
        """Suggest a fix for an error or bug."""
        error = params.get("error", "")
        code = params.get("code", "")
        context = params.get("context", "")

        if not error and not code:
            return self._fail("Provide either an error message or code to fix")

        fix = await self._ai_suggest_fix(error, code, context)
        return self._ok(
            summary=fix,
            data={"error": error, "code_length": len(code)},
        )

    async def _handle_review_pr(self, params: dict[str, Any]) -> dict[str, Any]:
        """Review a code diff."""
        diff = params.get("diff", "")
        description = params.get("description", "")

        if not diff:
            return self._fail("diff is required — provide the git diff or code changes")

        review = await self._ai_review_diff(diff, description)
        return self._ok(
            summary=review,
            data={"diff_length": len(diff), "description": description},
        )

    async def _handle_run_verifiers(self, params: dict[str, Any]) -> dict[str, Any]:
        """Run verifiers — delegates to local PC agent."""
        project = params.get("project", os.getcwd())
        verifier_type = params.get("type", "quick")  # quick | full

        # This is a stub — the local PC agent handles the actual execution
        return self._ok(
            summary=f"Verifier run requested for: {project}\nType: {verifier_type}\n\n"
                    "This task is routed to the local PC agent. If no local agent is connected, "
                    "run verifiers manually or connect a local agent.",
            data={
                "project": project,
                "type": verifier_type,
                "status": "pending_local_agent",
                "commands": {
                    "quick": ["python -m pytest --co -q 2>null || echo 'no tests'", "python -c 'import ast; [ast.parse(open(f).read()) for f in __import__(\"glob\").glob(\"**/*.py\", recursive=True)[:50]]'"],
                    "full": ["python -m pytest -x --tb=short 2>null || echo 'tests failed'", "python -m ruff check . 2>null || echo 'lint failed'"],
                }.get(verifier_type, []),
            },
        )

    async def _handle_explain_code(self, params: dict[str, Any]) -> dict[str, Any]:
        """Explain code."""
        code = params.get("code", "")
        language = params.get("language", "")

        if not code:
            return self._fail("code is required")

        explanation = await self._ai_explain(code, language)
        return self._ok(
            summary=explanation,
            data={"language": language, "code_length": len(code)},
        )

    async def _handle_optimize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Suggest optimizations."""
        code = params.get("code", "")
        goal = params.get("goal", "performance and readability")

        if not code:
            return self._fail("code is required")

        optimization = await self._ai_optimize(code, goal)
        return self._ok(
            summary=optimization,
            data={"goal": goal, "code_length": len(code)},
        )

    # ------------------------------------------------------------------
    # AI reasoning
    # ------------------------------------------------------------------

    async def _ai_call(self, prompt: str, max_tokens: int = 2000, temperature: float = 0.3) -> str:
        """Call litellm for code reasoning."""
        try:
            import litellm

            response = litellm.completion(
                model=os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": "You are an expert software engineer. Be specific, practical, and provide actionable advice. Use code blocks for code."},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.warning("AI call failed: %s", exc)
            return f"[AI unavailable: {exc}]"

    async def _ai_analyze(self, code: str, language: str, focus: str) -> str:
        lang_hint = f" (language: {language})" if language else ""
        prompt = f"""Analyze this code{lang_hint} for issues. Focus on: {focus}.

```{language or ''}
{code[:6000]}
```

Provide:
1. Bugs or logic errors (if any)
2. Anti-patterns or bad practices
3. Style or readability issues
4. Security concerns (if any)
5. Specific improvement suggestions with code examples

Be concise but thorough. Rate severity: 🔴 critical, 🟡 warning, 🟢 suggestion."""
        return await self._ai_call(prompt, max_tokens=2000)

    async def _ai_suggest_fix(self, error: str, code: str, context: str) -> str:
        parts = []
        if error:
            parts.append(f"Error: {error}")
        if code:
            parts.append(f"```\n{code[:4000]}\n```")
        if context:
            parts.append(f"Context: {context}")

        prompt = f"""Fix this issue:

{chr(10).join(parts)}

Provide:
1. Root cause analysis
2. The fix (with before/after code)
3. Explanation of why the fix works
4. Prevention tips"""
        return await self._ai_call(prompt, max_tokens=2000)

    async def _ai_review_diff(self, diff: str, description: str) -> str:
        prompt = f"""Review this code change:

{f'Description: {description}' if description else ''}

```diff
{diff[:6000]}
```

Provide a structured review:
1. Summary of changes
2. Potential issues or risks
3. Suggestions for improvement
4. What's done well
5. Verdict: ✅ Approve / ⚠️ Changes requested / ❌ Reject"""
        return await self._ai_call(prompt, max_tokens=2000, temperature=0.3)

    async def _ai_explain(self, code: str, language: str) -> str:
        prompt = f"""Explain this code in detail:

```{language or ''}
{code[:5000]}
```

Cover:
1. High-level purpose
2. Step-by-step walkthrough
3. Key patterns and techniques used
4. Any notable edge cases or assumptions

Write for a developer who understands programming but may not know this specific language well."""
        return await self._ai_call(prompt, max_tokens=2000)

    async def _ai_optimize(self, code: str, goal: str) -> str:
        prompt = f"""Suggest optimizations for this code. Goal: {goal}.

```{code[:5000]}
```

Provide:
1. Current bottlenecks or inefficiencies
2. Optimized version with before/after comparison
3. Trade-offs of each optimization
4. When NOT to apply these optimizations"""
        return await self._ai_call(prompt, max_tokens=2000)
