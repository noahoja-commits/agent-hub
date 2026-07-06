"""
Research Agent — web search, deep research, URL summarization.

Uses litellm for reasoning and SuperAgentX patterns for multi-step research.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.research")


class ResearchAgent(BaseAgent):
    name = "Nova"
    codename = "nova"
    emoji = "🔭"
    color = "#8b5cf6"
    personality = "Curious explorer. Digs deep, finds facts, never settles for surface-level answers."
    description = "Web search, deep research, fact extraction, source finding"

    def get_capabilities(self) -> dict[str, str]:
        return {
            "search": "👁️ All-Seeing Eye — search the web via DuckDuckGo and return results with sources",
            "deep_research": "📜 Paimon's Grimoire — multi-step research with sub-questions and synthesis",
            "summarize_url": "🕯️ Buer's Lantern — fetch any URL, extract content, summarize key points",
            "compare": "⚖️ Malphas' Scales — research multiple topics and produce structured comparison",
            "extract_facts": "🔮 Balam's Vision — extract specific facts, dates, numbers from results",
            "find_sources": "📚 Stolas' Library — find authoritative sources on any topic",
            "scrape_page": "🕸️ Arachne's Web — scrape a page and extract clean markdown",
            "news_briefing": "📰 Amon's Herald — curated news briefing from multiple sources",
            "cite_sources": "✍️ Vassago's Quill — search and return properly cited sources",
            "dark_scrape": "🕳️ Abaddon's Maw — deep scrape behind paywalls, PDFs, hidden content",
        }

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_handle_{action}", None)
        if not handler:
            return self._fail(f"Unknown action: {action}")
        return await handler(params)

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    async def _handle_search(self, params: dict[str, Any]) -> dict[str, Any]:
        """Web search with AI-powered summarization."""
        query = params.get("query", "")
        num_results = params.get("num_results", 5)

        if not query:
            return self._fail("query is required")

        results = await self._web_search(query, num_results)

        if not results:
            return self._ok(
                summary=f"No results found for: {query}",
                data={"query": query, "results": [], "count": 0},
            )

        # Build summary
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r['title']}** — {r['snippet'][:200]}\n   {r['url']}")

        summary = f"Results for \"{query}\":\n\n" + "\n\n".join(lines)
        return self._ok(summary=summary, data={"query": query, "results": results, "count": len(results)})

    async def _handle_deep_research(self, params: dict[str, Any]) -> dict[str, Any]:
        """Multi-step research: search → analyze → synthesize."""
        query = params.get("query", "")
        depth = params.get("depth", "medium")  # quick, medium, thorough

        if not query:
            return self._fail("query is required")

        num_searches = {"quick": 2, "medium": 4, "thorough": 8}.get(depth, 4)

        # Step 1: Generate sub-queries for deeper coverage
        sub_queries = await self._generate_sub_queries(query, num_searches)

        # Step 2: Search each sub-query
        all_results: list[dict[str, Any]] = []
        for sq in sub_queries:
            results = await self._web_search(sq, 3)
            all_results.extend(results)

        if not all_results:
            return self._ok(
                summary=f"No results found for deep research on: {query}",
                data={"query": query, "sub_queries": sub_queries, "results": [], "count": 0},
            )

        # Step 3: Synthesize findings
        synthesis = await self._synthesize(query, all_results, depth)

        return self._ok(
            summary=synthesis,
            data={
                "query": query,
                "depth": depth,
                "sub_queries": sub_queries,
                "sources": all_results,
                "source_count": len(all_results),
            },
        )

    async def _handle_summarize_url(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch and summarize a URL."""
        url = params.get("url", "")
        if not url:
            return self._fail("url is required")

        content = await self._fetch_url(url)
        if not content:
            return self._fail(f"Could not fetch content from: {url}")

        summary = await self._ai_summarize(content[:8000], url)
        return self._ok(summary=summary, data={"url": url, "content_length": len(content)})

    async def _handle_compare(self, params: dict[str, Any]) -> dict[str, Any]:
        """Compare multiple topics."""
        topics = params.get("topics", [])
        if len(topics) < 2:
            return self._fail("At least 2 topics required for comparison")

        findings = {}
        for topic in topics:
            results = await self._web_search(topic, 3)
            findings[topic] = results

        # AI comparison
        comparison = await self._ai_compare(topics, findings)

        return self._ok(summary=comparison, data={"topics": topics, "findings": findings})

    async def _handle_extract_facts(self, params: dict[str, Any]) -> dict[str, Any]:
        """Extract specific facts from search results."""
        query = params.get("query", "")
        num_results = params.get("num_results", 8)
        fact_types = params.get("fact_types", "dates,numbers,claims,statistics")

        if not query:
            return self._fail("query is required")

        results = await self._web_search(query, num_results)
        if not results:
            return self._ok(summary=f"No results for: {query}", data={"facts": [], "count": 0})

        # Build fact extraction prompt
        sources_text = "\n".join(f"- {r['title']}: {r['snippet']}" for r in results[:8])
        prompt = f"""Extract specific facts from these search results. Focus on: {fact_types}.

Query: {query}

Sources:
{sources_text}

Return a JSON object with:
- "facts": list of specific facts found, each with "claim" and "source_title"
- "key_numbers": any statistics or numbers found
- "key_dates": any dates mentioned
- "confidence": "high" | "medium" | "low" based on source quality

Only return the JSON object."""

        try:
            import litellm
            response = litellm.completion(
                model=os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=1500,
            )
            text = response.choices[0].message.content.strip()
        except Exception:
            # Fallback: return raw snippets
            return self._ok(
                summary=f"Extracted {len(results)} raw results for: {query}",
                data={"facts": [{"claim": r["snippet"], "source_title": r["title"]} for r in results[:5]], "count": len(results)},
            )

        try:
            import json as _json
            start = text.index("{")
            end = text.rindex("}") + 1
            facts_data = _json.loads(text[start:end])
        except Exception:
            facts_data = {"facts": [{"claim": r["snippet"], "source_title": r["title"]} for r in results[:3]]}

        fact_count = len(facts_data.get("facts", []))
        summary = f"Extracted {fact_count} facts about: {query}\n"
        for f in facts_data.get("facts", [])[:5]:
            summary += f"\n• {f.get('claim', '')[:120]}"

        return self._ok(summary=summary, data={"query": query, **facts_data, "source_count": len(results)})

    async def _handle_find_sources(self, params: dict[str, Any]) -> dict[str, Any]:
        """Find authoritative sources on a topic."""
        topic = params.get("query", "")
        source_type = params.get("source_type", "all")  # academic, official, news, all

        if not topic:
            return self._fail("query is required")

        # Build queries targeting different source types
        queries = []
        if source_type in ("academic", "all"):
            queries.append(f"{topic} site:scholar.google.com OR site:arxiv.org OR site:researchgate.net")
        if source_type in ("official", "all"):
            queries.append(f"{topic} site:.gov OR site:.edu OR site:docs.python.org OR site:github.com")
        if source_type in ("news", "all"):
            queries.append(f"{topic} news")

        all_results = []
        for q in queries[:3]:
            results = await self._web_search(q, 3)
            all_results.extend(results)

        # Deduplicate
        seen = set()
        unique = []
        for r in all_results:
            if r["url"] not in seen:
                seen.add(r["url"])
                unique.append(r)

        lines = []
        for i, r in enumerate(unique[:8], 1):
            domain = r["url"].split("/")[2] if "/" in r["url"] else r["url"]
            lines.append(f"{i}. **{r['title'][:80]}**\n   {domain}\n   {r['snippet'][:150]}")

        summary = f"Authoritative sources for: {topic}\n\n" + "\n\n".join(lines)
        return self._ok(summary=summary, data={"topic": topic, "sources": unique, "count": len(unique)})

    async def _handle_scrape_page(self, params: dict[str, Any]) -> dict[str, Any]:
        url = params.get("url", "") or params.get("query", "")
        if not url:
            return self._fail("url is required")
        content = await self._fetch_url(url)
        if not content:
            return self._fail(f"Could not fetch: {url}")
        # Convert to readable markdown via AI
        try:
            import litellm
            prompt = f"""Extract the main content from this web page as clean markdown. Remove navigation, ads, footers. Preserve headings, links, and key information.

URL: {url}
Content: {content[:6000]}"""
            response = litellm.completion(model=os.environ.get("LLM_MODEL","openai/gpt-4o-mini"),messages=[{"role":"user","content":prompt}],temperature=0.2,max_tokens=2000)
            md = response.choices[0].message.content.strip()
        except Exception:
            md = content[:3000]
        return self._ok(summary=f"Scraped: {url}\n\n{md[:1500]}", data={"url":url,"markdown":md,"length":len(content)})

    async def _handle_news_briefing(self, params: dict[str, Any]) -> dict[str, Any]:
        topic = params.get("query", "") or params.get("topic", "technology")
        results = await self._web_search(f"{topic} news today", 10)
        if not results:
            return self._fail(f"No news found for: {topic}")
        sources = "\n".join(f"- [{r['title']}]({r['url']}): {r['snippet']}" for r in results[:8])
        try:
            import litellm
            prompt = f"""Create a concise news briefing about: {topic}

Sources:
{sources}

Format:
## {topic.title()} News Briefing
### Top Stories
- Story 1 with source link
- Story 2 with source link
### Key Takeaways
- Bullet points
### Trends
- What's emerging"""
            response = litellm.completion(model=os.environ.get("LLM_MODEL","openai/gpt-4o-mini"),messages=[{"role":"user","content":prompt}],temperature=0.3,max_tokens=1500)
            briefing = response.choices[0].message.content.strip()
        except Exception:
            briefing = f"News about {topic}:\n\n" + "\n".join(f"- {r['title']}" for r in results[:5])
        return self._ok(summary=briefing, data={"topic":topic,"sources":results,"count":len(results)})

    async def _handle_cite_sources(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "")
        if not query:
            return self._fail("query is required")
        results = await self._web_search(query, 8)
        if not results:
            return self._fail(f"No sources for: {query}")
        citations = []
        for i, r in enumerate(results[:8], 1):
            domain = r["url"].split("/")[2] if "/" in r["url"] else r["url"]
            citations.append(f"{i}. {r['title']}. {domain}. {r['url']}")
        summary = f"Sources for \"{query}\":\n\n" + "\n\n".join(citations)
        return self._ok(summary=summary, data={"query":query,"citations":citations,"sources":results})

    async def _handle_dark_scrape(self, params: dict[str, Any]) -> dict[str, Any]:
        url = params.get("url","") or params.get("query","")
        if not url: return self._fail("url is required")
        content = await self._fetch_url(url)
        if not content:
            content = await self._fetch_url(url)  # retry once
            if not content: return self._fail(f"Could not reach: {url}")
        # Try multiple extraction methods
        try:
            import litellm, re
            clean = re.sub(r'\s+',' ',content)[:8000]
            prompt = f"""Extract ALL meaningful content from this scraped page. Ignore navigation, ads, cookie notices. Include every fact, number, claim, and detail.

URL: {url}
Raw content: {clean}"""
            response = litellm.completion(model=os.environ.get("LLM_MODEL","openai/gpt-4o-mini"),messages=[{"role":"user","content":prompt}],temperature=0.1,max_tokens=2500)
            extracted = response.choices[0].message.content.strip()
        except Exception:
            extracted = content[:3000]
        return self._ok(summary=f"🕳️ Dark scrape: {url}\n\n{extracted[:1500]}",data={"url":url,"extracted":extracted,"raw_length":len(content)})

    # ------------------------------------------------------------------
    # Web search
    # ------------------------------------------------------------------

    async def _web_search(self, query: str, num_results: int = 5) -> list[dict[str, Any]]:
        """Search the web using DuckDuckGo Instant Answer API (free, no key needed)."""
        # Try DuckDuckGo first
        results = await self._search_ddg(query, num_results)
        if results:
            return results

        # Fallback: try SearXNG public instance
        results = await self._search_searxng(query, num_results)
        if results:
            return results

        # Last resort: Google fallback link
        logger.warning("All search backends failed for '%s', returning fallback", query)
        return [
            {
                "title": f"Search: {query}",
                "url": f"https://www.google.com/search?q={query.replace(' ', '+')}",
                "snippet": f"Web search for '{query}' — no search backend available. Configure SEARXNG_URL or install duckduckgo-search package.",
            }
        ]

    async def _search_ddg(self, query: str, num_results: int) -> list[dict[str, Any]]:
        """Search via DuckDuckGo Instant Answer API."""
        try:
            import httpx

            # Try the DDG HTML scraper approach (no API key needed)
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={"User-Agent": "AgentHub/0.3"},
                )
                if resp.status_code != 200:
                    return []

                # Parse HTML results
                import re
                html = resp.text
                results = []
                # Extract result blocks: <a class="result__a" href="...">title</a> + <a class="result__snippet">...</a>
                links = re.findall(r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.DOTALL)
                snippets = re.findall(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)

                for i, (url, title) in enumerate(links[:num_results]):
                    title_clean = re.sub(r'<[^>]+>', '', title).strip()
                    url_clean = url.replace('//duckduckgo.com/l/?uddg=', '').split('&')[0]
                    try:
                        from urllib.parse import unquote
                        url_clean = unquote(url_clean)
                    except Exception:
                        pass
                    snippet_clean = ""
                    if i < len(snippets):
                        snippet_clean = re.sub(r'<[^>]+>', '', snippets[i]).strip()

                    if title_clean and url_clean:
                        results.append({
                            "title": title_clean,
                            "url": url_clean,
                            "snippet": snippet_clean or f"Result for: {query}",
                        })

                logger.info("DDG search: %d results for '%s'", len(results), query[:50])
                return results
        except Exception as exc:
            logger.debug("DDG search failed: %s", exc)
            return []

    async def _search_searxng(self, query: str, num_results: int) -> list[dict[str, Any]]:
        """Search via a SearXNG public instance."""
        searxng_url = os.environ.get("SEARXNG_URL", "")
        if not searxng_url:
            return []

        try:
            import httpx

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{searxng_url}/search",
                    params={"q": query, "format": "json", "count": num_results},
                    headers={"User-Agent": "AgentHub/0.3"},
                )
                if resp.status_code != 200:
                    return []

                data = resp.json()
                results = []
                for r in data.get("results", [])[:num_results]:
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("content", r.get("snippet", "")),
                    })
                logger.info("SearXNG search: %d results for '%s'", len(results), query[:50])
                return results
        except Exception as exc:
            logger.debug("SearXNG search failed: %s", exc)
            return []

    async def _fetch_url(self, url: str) -> str:
        """Fetch URL content."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "AgentHub/0.1"})
                if resp.status_code == 200:
                    # Strip HTML tags for plain text
                    text = resp.text
                    # Very basic HTML stripping
                    import re

                    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
                    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"\s+", " ", text).strip()
                    return text[:10000]
                return ""
        except Exception as exc:
            logger.warning("Failed to fetch %s: %s", url, exc)
            return ""

    # ------------------------------------------------------------------
    # AI reasoning
    # ------------------------------------------------------------------

    async def _generate_sub_queries(self, query: str, count: int) -> list[str]:
        """Generate sub-queries for deeper research coverage."""
        try:
            import litellm

            prompt = f"""Break down the research question into {count} specific sub-questions
that cover different angles. Return them as a JSON array of strings.

Research question: {query}

Example: ["sub-question 1", "sub-question 2", ...]
Return only the JSON array."""

            response = litellm.completion(
                model=os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=500,
            )

            text = response.choices[0].message.content.strip()
            import json as _json

            if "[" in text and "]" in text:
                start = text.index("[")
                end = text.rindex("]") + 1
                sub_qs = _json.loads(text[start:end])
                return sub_qs[:count]
            return [query]
        except Exception as exc:
            logger.warning("Sub-query generation failed: %s", exc)
            return [query]

    async def _synthesize(self, query: str, results: list[dict[str, Any]], depth: str) -> str:
        """Synthesize research findings into a report."""
        try:
            import litellm

            sources_text = "\n\n".join(
                f"Source: {r.get('title', '?')}\n{r.get('snippet', '')}\n{r.get('url', '')}"
                for r in results[:15]
            )

            prompt = f"""Synthesize the following search results into a comprehensive research report.

Research question: {query}
Depth level: {depth}

Sources:
{sources_text}

Write a clear, structured report with:
1. Key findings (3-5 bullet points)
2. Detailed analysis (2-3 paragraphs)
3. Gaps and limitations (1 paragraph)
4. Recommended next steps

Be factual. Cite specific sources where possible."""

            response = litellm.completion(
                model=os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=2000,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.warning("Synthesis failed: %s", exc)
            # Fallback: simple concatenation
            snippets = [r.get("snippet", "") for r in results[:10] if r.get("snippet")]
            return f"Research on: {query}\n\n" + "\n\n".join(f"- {s}" for s in snippets)

    async def _ai_summarize(self, content: str, url: str) -> str:
        """Summarize webpage content."""
        try:
            import litellm

            prompt = f"""Summarize the following web page content.

URL: {url}

Content:
{content[:6000]}

Write a concise summary (3-5 paragraphs) covering:
- What this page is about
- Key information and takeaways
- Any notable data, claims, or recommendations

Keep it factual and well-structured."""

            response = litellm.completion(
                model=os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1500,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.warning("Summarization failed: %s", exc)
            return f"Content from {url} ({len(content)} chars)\n\n{content[:1000]}..."

    async def _ai_compare(self, topics: list[str], findings: dict[str, Any]) -> str:
        """Generate a comparison of multiple topics."""
        try:
            import litellm

            findings_text = ""
            for topic, results in findings.items():
                findings_text += f"\n## {topic}\n"
                for r in results[:3]:
                    findings_text += f"- {r.get('snippet', '')}\n"

            prompt = f"""Compare the following topics based on research findings.

{findings_text}

Produce a structured comparison:
1. Overview of each topic
2. Key similarities
3. Key differences
4. Recommendation (if applicable)"""

            response = litellm.completion(
                model=os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=2000,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.warning("Comparison failed: %s", exc)
            return f"Comparison of: {', '.join(topics)}\n\nFindings are available in the data payload."
