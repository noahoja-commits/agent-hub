"""
Content Agent — creates documents, spreadsheets, slides, and written content.

Uses litellm for AI generation and Lark OpenAPI for doc creation.
Set LARK_APP_ID, LARK_APP_SECRET, and LARK_USER_ACCESS_TOKEN in env for live mode.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.content")

LARK_BASE = "https://open.larksuite.com/open-apis"


def _lark_headers() -> dict[str, str]:
    token = os.environ.get("LARK_USER_ACCESS_TOKEN", "") or os.environ.get("LARK_TENANT_ACCESS_TOKEN", "")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


class ContentAgent(BaseAgent):
    name = "Scribe"
    codename = "scribe"
    emoji = "✨"
    color = "#10b981"
    personality = "Wordsmith and creator. Crafts compelling content, structures ideas, makes your thoughts shine."
    description = "Blog posts, documents, reports, code generation, format conversion, email templates"

    def get_capabilities(self) -> dict[str, str]:
        return {
            "create_doc": "Create a document with AI-generated content on any topic",
            "create_spreadsheet": "Create a spreadsheet with structured data and formulas",
            "create_slides": "Create a slide deck with AI-generated outline and content",
            "write_blog_post": "Generate a blog post on any topic with SEO optimization",
            "format_report": "Generate a formatted report with sections, data tables, and conclusions",
            "generate_email_template": "Generate an email template for common scenarios",
            "generate_code": "Generate code snippets, scripts, or functions based on description",
            "translate_format": "Convert content between formats (markdown, HTML, plain text, JSON)",
            "seo_optimize": "Optimize content for SEO with keywords, meta descriptions, headings",
            "content_calendar": "Generate a content calendar with topics for a given theme",
        }

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_handle_{action}", None)
        if not handler:
            return self._fail(f"Unknown action: {action}")
        return await handler(params)

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    async def _handle_create_doc(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a Lark document with AI-generated content."""
        topic = params.get("topic", "")
        style = params.get("style", "professional")
        length = params.get("length", "medium")

        if not topic:
            return self._fail("topic is required")

        content = await self._ai_generate_doc(topic, style, length)
        doc_result = await self._create_lark_doc(f"{topic}", content)

        if doc_result:
            doc_url = doc_result.get("url", "")
            return self._ok(
                summary=f"Document created: \"{topic}\"\n{doc_url}\n\n{content[:300]}...",
                data={"title": topic, "url": doc_url, "content": content, "doc": doc_result},
            )

        return self._ok(
            summary=f"AI-generated document: \"{topic}\"\n\n{content[:800]}{'...' if len(content) > 800 else ''}",
            data={"title": topic, "content": content, "mode": "demo"},
        )

    async def _handle_create_spreadsheet(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a spreadsheet with structured data."""
        topic = params.get("topic", "")
        rows_count = params.get("rows", 10)

        if not topic:
            return self._fail("topic is required")

        sheet_data = await self._ai_generate_spreadsheet(topic, rows_count)
        sheet_result = await self._create_lark_sheet(topic, sheet_data)

        if sheet_result:
            return self._ok(
                summary=f"Spreadsheet created: \"{topic}\" with {len(sheet_data.get('rows', []))} rows",
                data={"title": topic, "url": sheet_result.get("url", ""), "data": sheet_data},
            )

        return self._ok(
            summary=f"AI-generated spreadsheet structure for: {topic}",
            data={"title": topic, "data": sheet_data, "mode": "demo"},
        )

    async def _handle_create_slides(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a slide deck."""
        topic = params.get("topic", "")
        slides_count = params.get("slides", 8)

        if not topic:
            return self._fail("topic is required")

        slides = await self._ai_generate_slides(topic, slides_count)
        slide_result = await self._create_lark_slides(topic, slides)

        if slide_result:
            return self._ok(
                summary=f"Slide deck created: \"{topic}\" ({len(slides)} slides)",
                data={"title": topic, "slides": slides, "url": slide_result.get("url", "")},
            )

        preview = "\n\n".join(f"Slide {i+1}: **{s['title']}**\n{s['content'][:100]}" for i, s in enumerate(slides[:5]))
        return self._ok(
            summary=f"AI-generated slide deck: \"{topic}\" ({len(slides)} slides)\n\n{preview}",
            data={"title": topic, "slides": slides, "mode": "demo"},
        )

    async def _handle_write_blog_post(self, params: dict[str, Any]) -> dict[str, Any]:
        """Generate a blog post."""
        topic = params.get("topic", "")
        tone = params.get("tone", "engaging")
        word_count = params.get("word_count", 800)

        if not topic:
            return self._fail("topic is required")

        blog = await self._ai_generate_blog(topic, tone, word_count)
        return self._ok(
            summary=f"Blog post: \"{topic}\"\n\n{blog[:600]}{'...' if len(blog) > 600 else ''}",
            data={"title": topic, "content": blog, "word_count": len(blog.split())},
        )

    async def _handle_format_report(self, params: dict[str, Any]) -> dict[str, Any]:
        """Generate a formatted report."""
        topic = params.get("topic", "")
        sections = params.get("sections", ["Executive Summary", "Analysis", "Findings", "Recommendations"])

        if not topic:
            return self._fail("topic is required")

        report = await self._ai_generate_report(topic, sections)
        return self._ok(
            summary=f"Report: \"{topic}\"\n\n{report[:600]}{'...' if len(report) > 600 else ''}",
            data={"title": topic, "content": report, "sections": sections},
        )

    async def _handle_generate_email_template(self, params: dict[str, Any]) -> dict[str, Any]:
        """Generate an email template."""
        scenario = params.get("scenario", "follow-up")
        tone = params.get("tone", "professional")

        template = await self._ai_generate_email_template(scenario, tone)
        return self._ok(
            summary=f"Email template: {scenario}\n\n{template[:500]}{'...' if len(template) > 500 else ''}",
            data={"scenario": scenario, "template": template},
        )

    async def _handle_generate_code(self, params: dict[str, Any]) -> dict[str, Any]:
        """Generate code based on description."""
        description = params.get("query", "") or params.get("description", "")
        language = params.get("language", "python")
        if not description:
            return self._fail("query is required — describe what code to generate")

        prompt = f"""Write {language} code that: {description}

Include:
- Clean, well-commented code
- Error handling where appropriate
- Type hints if the language supports them
- A brief explanation of how it works

Return the code in a ```{language} code block followed by the explanation."""
        code = await self._ai_generate(prompt, max_tokens=2000, temperature=0.3)
        return self._ok(summary=code, data={"language": language, "description": description, "code": code})

    async def _handle_translate_format(self, params: dict[str, Any]) -> dict[str, Any]:
        """Convert content between formats."""
        content = params.get("content", "") or params.get("query", "")
        from_fmt = params.get("from", "auto")
        to_fmt = params.get("to", "markdown")

        if not content:
            return self._fail("content is required")

        prompt = f"""Convert the following content from {from_fmt} to {to_fmt} format.
Preserve all information, structure, and meaning.

Content:
{content[:5000]}

Return ONLY the converted content, no explanations."""
        converted = await self._ai_generate(prompt, max_tokens=2000, temperature=0.1)
        return self._ok(summary=f"Converted to {to_fmt}:\n\n{converted[:600]}",
                        data={"from": from_fmt, "to": to_fmt, "converted": converted})

    async def _handle_seo_optimize(self, params: dict[str, Any]) -> dict[str, Any]:
        content = params.get("content","") or params.get("query","")
        topic = params.get("topic","")
        if not content:
            return self._fail("content is required")
        prompt = f"""Optimize this content for SEO. Return JSON with:
- "optimized_content": the full rewritten content
- "meta_description": 155-char meta description
- "keywords": [list of 5-10 target keywords]
- "heading_structure": suggested H1/H2/H3 structure
- "improvements": [list of specific SEO improvements made]

Topic: {topic or 'auto-detect'}
Content: {content[:4000]}"""
        try:
            import litellm, json as _json
            response = litellm.completion(model=os.environ.get("LLM_MODEL","openai/gpt-4o-mini"),messages=[{"role":"user","content":prompt}],temperature=0.3,max_tokens=2000)
            text = response.choices[0].message.content.strip()
            start = text.index("{"); end = text.rindex("}")+1
            seo = _json.loads(text[start:end])
        except Exception:
            seo = {"optimized_content":content,"meta_description":"","keywords":[],"improvements":["AI optimization unavailable"]}
        return self._ok(summary=seo.get("optimized_content",content)[:1500],data=seo)

    async def _handle_content_calendar(self, params: dict[str, Any]) -> dict[str, Any]:
        theme = params.get("theme","") or params.get("query","")
        count = params.get("count",7)
        if not theme:
            return self._fail("theme is required")
        prompt = f"""Generate a {count}-day content calendar for the theme: {theme}

For each day, provide:
- Title (compelling, SEO-friendly)
- Content type (blog post, social, video script, newsletter, etc.)
- Brief description (1-2 sentences)
- Target keywords

Return as JSON array: [{{"day":1,"title":"...","type":"...","description":"...","keywords":["..."]}},...]"""
        try:
            import litellm, json as _json
            response = litellm.completion(model=os.environ.get("LLM_MODEL","openai/gpt-4o-mini"),messages=[{"role":"user","content":prompt}],temperature=0.7,max_tokens=2000)
            text = response.choices[0].message.content.strip()
            start = text.index("["); end = text.rindex("]")+1
            calendar = _json.loads(text[start:end])
        except Exception:
            calendar = [{"day":i+1,"title":f"{theme} - Day {i+1}","type":"blog post","description":"","keywords":[]} for i in range(count)]
        lines = [f"📅 Content Calendar: {theme}\n"]
        for d in calendar:
            lines.append(f"\nDay {d['day']}: **{d['title']}** ({d['type']})")
            lines.append(f"  {d.get('description','')[:120]}")
        return self._ok(summary="\n".join(lines),data={"calendar":calendar,"theme":theme})

    # ------------------------------------------------------------------
    # AI generation
    # ------------------------------------------------------------------

    async def _ai_generate(self, prompt: str, max_tokens: int = 2000, temperature: float = 0.7) -> str:
        """Call litellm for content generation."""
        try:
            import litellm

            response = litellm.completion(
                model=os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.warning("AI generation failed: %s", exc)
            return f"[AI generation unavailable: {exc}]"

    async def _ai_generate_doc(self, topic: str, style: str, length: str) -> str:
        length_map = {"short": "300-500", "medium": "800-1200", "long": "1500-2500"}
        words = length_map.get(length, "800-1200")

        prompt = f"""Write a {style} document about: {topic}

Length: {words} words. Use markdown formatting with headings, bullet points, and
a clear structure. Include an introduction, body sections, and a conclusion.
Write naturally and avoid AI-sounding phrases like "in conclusion" or "let me explain"."""
        return await self._ai_generate(prompt, max_tokens=3000)

    async def _ai_generate_spreadsheet(self, topic: str, rows: int) -> dict[str, Any]:
        prompt = f"""Generate structured data for a spreadsheet about: {topic}

Return a JSON object with:
- "headers": list of column names (4-6 columns)
- "rows": list of lists with {rows} data rows

Realistic, useful data. Return ONLY the JSON object: {{"headers": [...], "rows": [[...], ...]}}"""
        result = await self._ai_generate(prompt, max_tokens=2000, temperature=0.5)
        try:
            import json as _json
            start = result.index("{")
            end = result.rindex("}") + 1
            return _json.loads(result[start:end])
        except Exception:
            return {"headers": ["Item", "Value", "Notes"], "rows": [[f"Data {i}", str(i * 100), "Auto-generated"] for i in range(1, rows + 1)]}

    async def _ai_generate_slides(self, topic: str, count: int) -> list[dict[str, str]]:
        prompt = f"""Create a {count}-slide presentation about: {topic}

Return a JSON array of slides. Each slide has "title" and "content".
Slide 1 is the title slide. Include a logical flow: intro, key points, details, conclusion.

Return ONLY the JSON array: [{{"title": "...", "content": "..."}}, ...]"""
        result = await self._ai_generate(prompt, max_tokens=2000, temperature=0.7)
        try:
            import json as _json
            start = result.index("[")
            end = result.rindex("]") + 1
            return _json.loads(result[start:end])
        except Exception:
            return [{"title": topic, "content": f"Presentation about {topic}. Content generation unavailable."}]

    async def _ai_generate_blog(self, topic: str, tone: str, word_count: int) -> str:
        prompt = f"""Write a {tone} blog post about: {topic}

Target {word_count} words. Use markdown formatting. Include:
- An attention-grabbing title
- Introduction that hooks the reader
- 3-5 body sections with clear subheadings
- Practical takeaways or actionable advice
- Natural conclusion

Write as a human expert would — avoid AI clichés."""
        return await self._ai_generate(prompt, max_tokens=2500)

    async def _ai_generate_report(self, topic: str, sections: list[str]) -> str:
        sections_list = "\n".join(f"- {s}" for s in sections)
        prompt = f"""Write a professional report about: {topic}

Sections to include:
{sections_list}

Use markdown formatting with:
- # Title
- ## Section headings
- Bullet points for key findings
- **Bold** for emphasis
- Tables where data would help (use markdown tables)
- Clear, factual tone

Write naturally and thoroughly."""
        return await self._ai_generate(prompt, max_tokens=3000, temperature=0.4)

    async def _ai_generate_email_template(self, scenario: str, tone: str) -> str:
        prompt = f"""Write a {tone} email template for: {scenario}

Include:
- Subject line
- Greeting
- Body (3-4 paragraphs)
- Call to action
- Professional sign-off

Use [brackets] for placeholders the user should fill in."""
        return await self._ai_generate(prompt, max_tokens=1000)

    # ------------------------------------------------------------------
    # Lark API integration
    # ------------------------------------------------------------------

    async def _create_lark_doc(self, title: str, content: str) -> dict[str, Any] | None:
        """Create a Lark Doc via OpenAPI."""
        headers = _lark_headers()
        if not headers["Authorization"].strip("Bearer "):
            return None

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                # Create doc
                resp = await client.post(
                    f"{LARK_BASE}/docx/v1/documents",
                    headers=headers,
                    json={"title": title},
                )
                if resp.status_code not in (200, 201):
                    logger.warning("Doc creation failed: %d", resp.status_code)
                    return None

                doc_data = resp.json().get("data", {})
                doc_id = doc_data.get("document", {}).get("document_id", "")

                if doc_id:
                    # Write content
                    blocks = self._markdown_to_doc_blocks(content)
                    await client.patch(
                        f"{LARK_BASE}/docx/v1/documents/{doc_id}/blocks/{doc_data.get('document', {}).get('root_block_id', doc_id)}/children",
                        headers=headers,
                        json={"children": blocks, "index": 0},
                    )

                return {
                    "doc_id": doc_id,
                    "url": f"https://bytedance.feishu.cn/docx/{doc_id}" if doc_id else "",
                    "title": title,
                }
        except Exception as exc:
            logger.warning("Lark doc creation failed: %s", exc)
            return None

    async def _create_lark_sheet(self, title: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Create a Lark spreadsheet."""
        headers = _lark_headers()
        if not headers["Authorization"].strip("Bearer "):
            return None

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{LARK_BASE}/sheets/v3/spreadsheets",
                    headers=headers,
                    json={"title": title},
                )
                if resp.status_code not in (200, 201):
                    return None

                sheet_data = resp.json().get("data", {}).get("spreadsheet", {})
                spreadsheet_token = sheet_data.get("spreadsheet_token", "")
                sheet_id = sheet_data.get("sheets", [{}])[0].get("sheet_id", "")

                if spreadsheet_token and sheet_id and data.get("headers"):
                    # Write headers and data
                    values = [data["headers"]]
                    values.extend(data.get("rows", [])[:100])

                    await client.post(
                        f"{LARK_BASE}/sheets/v2/spreadsheets/{spreadsheet_token}/values",
                        headers=headers,
                        json={
                            "valueRange": {
                                "range": f"{sheet_id}!A1:Z{len(values)}",
                                "values": values,
                            }
                        },
                    )

                return {
                    "spreadsheet_token": spreadsheet_token,
                    "url": f"https://bytedance.feishu.cn/sheets/{spreadsheet_token}" if spreadsheet_token else "",
                    "title": title,
                }
        except Exception as exc:
            logger.warning("Lark sheet creation failed: %s", exc)
            return None

    async def _create_lark_slides(self, title: str, slides: list[dict[str, str]]) -> dict[str, Any] | None:
        """Create Lark slides."""
        headers = _lark_headers()
        if not headers["Authorization"].strip("Bearer "):
            return None

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{LARK_BASE}/slides/v1/presentations",
                    headers=headers,
                    json={"title": title},
                )
                if resp.status_code not in (200, 201):
                    return None

                pres_data = resp.json().get("data", {}).get("presentation", {})
                pres_id = pres_data.get("id", "")

                return {
                    "presentation_id": pres_id,
                    "url": f"https://bytedance.feishu.cn/slides/{pres_id}" if pres_id else "",
                    "title": title,
                    "slides_count": len(slides),
                }
        except Exception as exc:
            logger.warning("Lark slides creation failed: %s", exc)
            return None

    def _markdown_to_doc_blocks(self, md: str) -> list[dict[str, Any]]:
        """Very basic markdown → Lark Doc blocks conversion."""
        blocks = []
        for line in md.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("# "):
                blocks.append({
                    "block_type": 3,  # heading1
                    "heading1": {"elements": [{"text_run": {"content": line[2:]}}]},
                })
            elif line.startswith("## "):
                blocks.append({
                    "block_type": 4,  # heading2
                    "heading2": {"elements": [{"text_run": {"content": line[3:]}}]},
                })
            elif line.startswith("- "):
                blocks.append({
                    "block_type": 8,  # bullet
                    "bullet": {"elements": [{"text_run": {"content": line[2:]}}]},
                })
            else:
                blocks.append({
                    "block_type": 2,  # text
                    "text": {"elements": [{"text_run": {"content": line}}]},
                })
        return blocks[:100]  # Lark limit
