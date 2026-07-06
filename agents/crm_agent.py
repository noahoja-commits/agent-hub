"""
Belial 📞 — CRM / Sales Agent
Cold call scripts, lead tracking, follow-up sequences, deal pipeline management.
"""
from __future__ import annotations
import logging, os, json
from typing import Any
from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.crm")

class CRMAgent(BaseAgent):
    name = "Belial"
    emoji = "📞"
    color = "#cc6600"
    personality = "Every lead is a soul to claim. I craft the words that close deals."
    codename = "belial"
    description = "CRM & Sales — cold call scripts, lead tracking, follow-ups, deal pipeline"

    def get_capabilities(self) -> dict[str, str]:
        return {
            "cold_call_script": "Generate a cold calling script for a specific prospect type",
            "follow_up_email": "Write a follow-up email sequence for a lead",
            "objection_handler": "Generate responses to common sales objections",
            "deal_analysis": "Analyze a deal — risk factors, negotiation leverage, next steps",
            "pitch_deck_outline": "Generate a pitch deck outline for investors or clients",
            "lead_qualifier": "Qualify a lead based on BANT or MEDDIC framework",
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
        except Exception as e:
            return f"[AI: {e}]"

    async def _h_cold_call_script(self, p):
        prospect = p.get("prospect","") or p.get("query","")
        industry = p.get("industry","real estate")
        if not prospect: return self._fail("prospect required — who are you calling?")
        prompt = f"""Write a cold calling script for a {industry} prospect: {prospect}

Include:
1. Opening hook (first 10 seconds)
2. Value proposition (why they should care)
3. 3 qualifying questions
4. Common objection → response
5. Call to action (next step)

Keep it natural, not salesy. Write for a human voice."""
        script = await self._ai(prompt)
        return self._ok(summary=script, data={"prospect":prospect,"industry":industry})

    async def _h_follow_up_email(self, p):
        lead = p.get("lead","") or p.get("query","")
        stage = p.get("stage","first follow-up")
        if not lead: return self._fail("lead name/description required")
        prompt = f"""Write a {stage} email for lead: {lead}

Include:
- Subject line
- Personalized opening
- Value reminder
- Soft call to action
- Professional sign-off

Keep it concise. Sound like a real person, not a template."""
        email = await self._ai(prompt)
        return self._ok(summary=email, data={"lead":lead,"stage":stage})

    async def _h_objection_handler(self, p):
        objection = p.get("objection","") or p.get("query","")
        context = p.get("context","sales call")
        if not objection: return self._fail("objection required")
        prompt = f"""Handle this sales objection in a {context} context: "{objection}"

Provide:
1. Acknowledge & validate (don't argue)
2. Reframe the concern
3. Provide evidence or example
4. Bridge to next point
5. Alternative response (aggressive approach)"""
        response = await self._ai(prompt)
        return self._ok(summary=response, data={"objection":objection})

    async def _h_deal_analysis(self, p):
        deal = p.get("deal","") or p.get("query","")
        if not deal: return self._fail("deal description required")
        prompt = f"""Analyze this deal: {deal}

Provide:
- Risk factors (3-5)
- Negotiation leverage points
- Red flags
- Recommended next steps
- Estimated close probability (low/medium/high) with reasoning"""
        analysis = await self._ai(prompt, temp=0.3)
        return self._ok(summary=analysis, data={"deal":deal})

    async def _h_pitch_deck_outline(self, p):
        company = p.get("company","") or p.get("query","")
        audience = p.get("audience","investors")
        if not company: return self._fail("company description required")
        prompt = f"""Create a pitch deck outline for: {company}\nAudience: {audience}

For each slide (10-12 slides):
- Slide title
- Key message (1 sentence)
- What to include (bullets)
- Design tip

Structure: Problem → Solution → Market → Traction → Team → Financials → Ask"""
        outline = await self._ai(prompt, temp=0.5)
        return self._ok(summary=outline, data={"company":company,"audience":audience})

    async def _h_lead_qualifier(self, p):
        lead = p.get("lead","") or p.get("query","")
        framework = p.get("framework","BANT")
        if not lead: return self._fail("lead description required")
        prompt = f"""Qualify this lead using the {framework} framework: {lead}

For each criterion, rate: ✅ Strong / ⚠️ Unclear / ❌ Weak
Provide specific evidence and recommended next action.

Overall score: Hot / Warm / Cold"""
        result = await self._ai(prompt, temp=0.3)
        return self._ok(summary=result, data={"lead":lead,"framework":framework})
