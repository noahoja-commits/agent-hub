"""
Fama 📢 — Social Media Agent
Content distribution, post scheduling, cross-platform analytics.
"""
from __future__ import annotations
import logging, os, json
from typing import Any
from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.social")

class SocialAgent(BaseAgent):
    name = "Fama"
    emoji = "📢"
    color = "#cc44cc"
    personality = "Rumors, fame, reputation. I spread your words across the digital realm."
    codename = "fama"
    description = "Social media — post creation, scheduling, cross-platform, analytics"

    def get_capabilities(self) -> dict[str, str]:
        return {
            "create_post": "Create a social media post optimized for a specific platform",
            "thread": "Generate a Twitter/X thread from a topic",
            "hashtag_strategy": "Suggest optimal hashtags for a post",
            "content_calendar": "Generate a weekly social media content calendar",
            "bio_generator": "Generate a compelling social media bio",
            "engagement_reply": "AI-draft replies to social media comments/messages",
        }

    async def execute(self, action, params):
        h = getattr(self, f"_h_{action}", None)
        if not h: return self._fail(f"Unknown: {action}")
        return await h(params)

    async def _ai(self, prompt, temp=0.7, tokens=1500):
        try:
            import litellm
            r = litellm.completion(model=os.environ.get("LLM_MODEL","openai/gpt-4o-mini"), messages=[{"role":"user","content":prompt}], temperature=temp, max_tokens=tokens)
            return r.choices[0].message.content.strip()
        except Exception as e: return f"[AI: {e}]"

    async def _h_create_post(self, p):
        topic = p.get("topic","") or p.get("query","")
        platform = p.get("platform","twitter")
        tone = p.get("tone","engaging")
        if not topic: return self._fail("topic required")
        limits = {"twitter":280,"linkedin":3000,"instagram":2200,"facebook":5000,"tiktok":150}
        limit = limits.get(platform, 500)
        prompt = f"""Write a {tone} social media post for {platform} about: {topic}

Max {limit} characters. Include:
- Hook in first line
- Value or insight
- Call to action
- {2 if platform in ('twitter','linkedin') else 5} relevant hashtags

Write ONLY the post. No explanations."""
        post = await self._ai(prompt, tokens=min(limit, 800))
        return self._ok(summary=post, data={"platform":platform,"topic":topic,"char_count":len(post)})

    async def _h_thread(self, p):
        topic = p.get("topic","") or p.get("query","")
        tweets = p.get("tweets", 5)
        if not topic: return self._fail("topic required")
        prompt = f"""Write a {tweets}-tweet Twitter/X thread about: {topic}

Format:
1/ [hook tweet — grab attention]
2/ [body — context, data, story]
3/ [body — deeper insight]
4/ [body — twist or counterpoint]
N/ [conclusion + CTA]

Make each tweet standalone readable. Use line breaks. Max 280 chars each."""
        thread = await self._ai(prompt, tokens=2000)
        return self._ok(summary=thread, data={"topic":topic,"tweets":tweets})

    async def _h_hashtag_strategy(self, p):
        topic = p.get("topic","") or p.get("query","")
        platform = p.get("platform","instagram")
        if not topic: return self._fail("topic required")
        prompt = f"""Suggest a hashtag strategy for a post about: {topic} on {platform}

Return JSON array:
- "primary": [3-5 broad, high-volume hashtags]
- "niche": [5-8 specific, targeted hashtags]
- "branded": [1-2 unique branded hashtags]

Return ONLY the JSON."""
        strategy = await self._ai(prompt, temp=0.5)
        return self._ok(summary=strategy, data={"topic":topic,"platform":platform})

    async def _h_content_calendar(self, p):
        theme = p.get("theme","") or p.get("query","")
        platforms = p.get("platforms",["twitter","linkedin"])
        if not theme: return self._fail("theme required")
        prompt = f"""Generate a 7-day social media content calendar for theme: {theme}
Platforms: {', '.join(platforms)}

For each day, provide:
- Day & theme
- Post idea for each platform
- Best posting time

Format as a clear weekly plan."""
        calendar = await self._ai(prompt, tokens=2000)
        return self._ok(summary=calendar, data={"theme":theme})

    async def _h_bio_generator(self, p):
        about = p.get("about","") or p.get("query","")
        platform = p.get("platform","twitter")
        tone = p.get("tone","professional with personality")
        if not about: return self._fail("describe yourself/your brand")
        limits = {"twitter":160,"linkedin":260,"instagram":150,"tiktok":80}
        limit = limits.get(platform, 200)
        prompt = f"""Write a {tone} bio for {platform} ({limit} chars max) about:
{about}

Include: who you are, what you do, value prop, 1 emoji, CTA or link hint."""
        bio = await self._ai(prompt, tokens=200)
        return self._ok(summary=bio, data={"platform":platform,"char_count":len(bio)})

    async def _h_engagement_reply(self, p):
        comment = p.get("comment","") or p.get("query","")
        tone = p.get("tone","friendly and helpful")
        if not comment: return self._fail("comment text required")
        prompt = f"""Draft a {tone} reply to this social media comment:
"{comment}"

Keep it genuine and conversational. Sound human."""
        reply = await self._ai(prompt, tokens=300)
        return self._ok(summary=reply, data={"comment":comment})
