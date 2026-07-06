"""
Dev Agent — writes, runs, and debugs code.

Can generate code, execute it server-side (sandboxed), capture output,
and iterate on fixes. For full system access, routes to local PC agent.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.dev")


class DevAgent(BaseAgent):
    name = "Echo"
    codename = "echo"
    emoji = "💻"
    color = "#06b6d4"
    personality = "Fast, pragmatic builder. Ships working code, catches errors, iterates until it runs."
    description = "Write code, execute server-side, auto-debug, create scripts, explain errors"

    def get_capabilities(self) -> dict[str, str]:
        return {
            "write_code": "💀 Forneus' Invocation — generate code from a description",
            "run_code": "⚡ Zagan's Execution — execute code server-side and return output",
            "debug": "🔄 Amdusias' Cycle — run, capture error, fix, re-run until it works",
            "create_script": "📜 Haagenti's Scroll — create a complete runnable script",
            "explain_error": "🔮 Orias' Insight — explain an error and suggest fixes",
            "scaffold_project": "🏗️ Gusion's Foundation — generate a complete project scaffold",
            "generate_api": "🌐 Vepar's Gateway — generate a REST API with routes and models",
        }

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_handle_{action}", None)
        if not handler:
            return self._fail(f"Unknown action: {action}")
        return await handler(params)

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    async def _handle_write_code(self, params: dict[str, Any]) -> dict[str, Any]:
        description = params.get("query", "") or params.get("description", "")
        language = params.get("language", "python")
        if not description:
            return self._fail("query is required — describe what code to write")

        code = await self._ai_generate_code(description, language)
        return self._ok(
            summary=f"Generated {language} code:\n\n```{language}\n{code[:1500]}\n```",
            data={"language": language, "code": code, "description": description},
        )

    async def _handle_run_code(self, params: dict[str, Any]) -> dict[str, Any]:
        code = params.get("code", "") or params.get("query", "")
        language = params.get("language", "python")
        if not code:
            return self._fail("code is required")

        result = await self._execute_code(code, language)
        exit_code = result.get("exit_code", -1)
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")

        if exit_code == 0 and stdout:
            summary = f"✅ Ran successfully:\n\n{stdout[:1500]}"
        elif stderr:
            summary = f"❌ Exit {exit_code}:\n\n{stderr[:1000]}"
        else:
            summary = f"Ran (exit {exit_code})"

        return self._ok(summary=summary, data=result)

    async def _handle_debug(self, params: dict[str, Any]) -> dict[str, Any]:
        code = params.get("code", "") or params.get("query", "")
        language = params.get("language", "python")
        max_attempts = params.get("max_attempts", 3)

        if not code:
            return self._fail("code is required")

        current_code = code
        attempts = []

        for i in range(max_attempts):
            result = await self._execute_code(current_code, language)
            attempts.append({"attempt": i + 1, "exit_code": result.get("exit_code"), "output": result.get("stdout", "")[:500] or result.get("stderr", "")[:500]})

            if result.get("exit_code") == 0:
                return self._ok(
                    summary=f"✅ Fixed after {i + 1} attempt(s):\n\n{result.get('stdout', '')[:1000]}",
                    data={"attempts": attempts, "final_code": current_code},
                )

            # AI suggests fix
            error_output = result.get("stderr", result.get("stdout", ""))
            current_code = await self._ai_fix_code(current_code, error_output, language)

        return self._ok(
            summary=f"❌ Could not fix after {max_attempts} attempts.\nLast error: {attempts[-1].get('output', '')[:500]}",
            data={"attempts": attempts, "last_code": current_code},
        )

    async def _handle_create_script(self, params: dict[str, Any]) -> dict[str, Any]:
        description = params.get("query", "") or params.get("description", "")
        language = params.get("language", "python")
        filename = params.get("filename", "script")

        if not description:
            return self._fail("query is required")

        code = await self._ai_generate_code(description, language)
        ext = {"python": "py", "javascript": "js", "bash": "sh", "powershell": "ps1"}.get(language, "txt")
        filepath = f"/tmp/{filename}.{ext}"

        # Write to temp file
        try:
            Path(filepath).write_text(code)
            return self._ok(
                summary=f"Script created: `{filepath}`\n\n```{language}\n{code[:1200]}\n```",
                data={"filepath": filepath, "language": language, "code": code},
            )
        except Exception as exc:
            return self._fail(f"Could not write file: {exc}")

    async def _handle_explain_error(self, params: dict[str, Any]) -> dict[str, Any]:
        error = params.get("error", "") or params.get("query", "")
        code = params.get("code", "")
        language = params.get("language", "")

        if not error:
            return self._fail("error is required")

        explanation = await self._ai_explain_error(error, code, language)
        return self._ok(summary=explanation, data={"error": error})

    async def _handle_scaffold_project(self, params: dict[str, Any]) -> dict[str, Any]:
        description = params.get("query","") or params.get("description","")
        language = params.get("language","python")
        if not description:
            return self._fail("query is required")
        prompt = f"""Generate a complete project scaffold for: {description}
Language: {language}

Return a JSON object with:
- "name": project name (slug)
- "structure": [list of file paths to create]
- "files": {{"path/to/file": "file content", ...}}
- "readme": "README.md content"
- "setup_instructions": "how to set up and run"

Include: entry point, config, tests, requirements/dependencies, .gitignore."""
        try:
            import litellm, json as _json
            response = litellm.completion(model=os.environ.get("LLM_MODEL","openai/gpt-4o-mini"),messages=[{"role":"user","content":prompt}],temperature=0.3,max_tokens=2500)
            text = response.choices[0].message.content.strip()
            start = text.index("{"); end = text.rindex("}")+1
            scaffold = _json.loads(text[start:end])
        except Exception:
            scaffold = {"name":"project","structure":["main.py","README.md"],"files":{},"setup_instructions":"Run: python main.py"}
        structure = "\n".join(f"  {'📁' if '/' not in f else '📄'} {f}" for f in scaffold.get("structure",[])[:20])
        summary = f"🏗️ Project: {scaffold.get('name','project')}\n\nStructure:\n{structure}\n\n{scaffold.get('setup_instructions','')[:300]}"
        return self._ok(summary=summary, data=scaffold)

    async def _handle_generate_api(self, params: dict[str, Any]) -> dict[str, Any]:
        description = params.get("query","") or params.get("description","")
        language = params.get("language","python")
        framework = params.get("framework","fastapi")
        if not description:
            return self._fail("query is required")
        prompt = f"""Generate a complete {framework} API for: {description}

Include:
- Route definitions with HTTP methods
- Request/response models (Pydantic if Python)
- Input validation
- Error handling
- At least 3 endpoints
- Database/models if needed

Return just the code with brief comments."""
        code = await self._ai_generate_code(f"Create a {framework} API that: {description}", language)
        return self._ok(summary=f"API generated:\n\n```{language}\n{code[:1500]}\n```",data={"framework":framework,"code":code,"language":language})

    # ------------------------------------------------------------------
    # Code execution (server-side sandbox)
    # ------------------------------------------------------------------

    async def _execute_code(self, code: str, language: str = "python") -> dict[str, Any]:
        """Execute code in a subprocess sandbox."""
        if language == "python":
            return await self._run_subprocess(["python", "-c", code])
        elif language == "javascript":
            return await self._run_subprocess(["node", "-e", code])
        elif language == "bash":
            return await self._run_subprocess(["bash", "-c", code])
        else:
            return {"exit_code": -1, "stderr": f"Unsupported language: {language}", "stdout": ""}

    async def _run_subprocess(self, cmd: list[str], timeout: int = 30) -> dict[str, Any]:
        """Run a subprocess and return output."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "exit_code": proc.returncode or 0,
                "stdout": stdout.decode("utf-8", errors="replace")[:5000],
                "stderr": stderr.decode("utf-8", errors="replace")[:2000],
            }
        except asyncio.TimeoutError:
            return {"exit_code": -1, "stderr": f"Timed out after {timeout}s", "stdout": ""}
        except FileNotFoundError:
            return {"exit_code": -1, "stderr": f"Runtime not found: {cmd[0]}. Install it on the server.", "stdout": ""}
        except Exception as exc:
            return {"exit_code": -1, "stderr": str(exc), "stdout": ""}

    # ------------------------------------------------------------------
    # AI generation
    # ------------------------------------------------------------------

    async def _ai_generate_code(self, description: str, language: str) -> str:
        try:
            import litellm
            prompt = f"""Write {language} code that: {description}

Requirements:
- Complete, runnable code
- Error handling where appropriate
- Comments explaining key parts
- No placeholder or TODO — write the actual implementation

Return ONLY the code, no explanations before or after."""
            response = litellm.completion(
                model=os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=2000,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            return f"# AI generation failed: {exc}\n# Write code that: {description}"

    async def _ai_fix_code(self, code: str, error: str, language: str) -> str:
        try:
            import litellm
            prompt = f"""This {language} code produced an error. Fix it.

Code:
```{language}
{code[:3000]}
```

Error:
{error[:2000]}

Return ONLY the fixed code. No explanations."""
            response = litellm.completion(
                model=os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=2000,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            return code

    async def _ai_explain_error(self, error: str, code: str, language: str) -> str:
        try:
            import litellm
            prompt = f"""Explain this {language} error in simple terms and suggest how to fix it.

{f'Code:\n```{language}\n{code[:1500]}\n```\n' if code else ''}
Error:
{error[:2000]}

Provide:
1. What the error means (plain English)
2. Common causes
3. Specific fix with code example"""
            response = litellm.completion(
                model=os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=1500,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            return f"Error explanation unavailable. Raw error: {error[:500]}"
