"""
Hermes 🌐 — Translation Agent
Multi-language translation with context awareness and localization.
"""
from __future__ import annotations
import logging, os
from typing import Any
from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.translation")

class TranslationAgent(BaseAgent):
    name = "Hermes"
    emoji = "🌐"
    color = "#44cc44"
    personality = "I speak in every tongue. No barrier stands between minds that wish to understand."
    codename = "hermes"
    description = "Translation — multi-language, localization, language detection, cultural adaptation"

    def get_capabilities(self) -> dict[str, str]:
        return {
            "translate": "Translate text between any two languages",
            "detect_language": "Detect the language of a given text",
            "localize": "Localize content for a specific region (not just translate — culturally adapt)",
            "summarize_translate": "Summarize foreign text, then translate the summary",
            "translate_code_comments": "Translate code comments and docstrings between languages",
            "language_list": "List supported languages and their codes",
        }

    async def execute(self, action, params):
        h = getattr(self, f"_h_{action}", None)
        if not h: return self._fail(f"Unknown: {action}")
        return await h(params)

    async def _ai(self, prompt, temp=0.3, tokens=1500):
        try:
            import litellm
            r = litellm.completion(model=os.environ.get("LLM_MODEL","openai/gpt-4o-mini"), messages=[{"role":"user","content":prompt}], temperature=temp, max_tokens=tokens)
            return r.choices[0].message.content.strip()
        except Exception as e: return f"[AI: {e}]"

    async def _h_translate(self, p):
        text = p.get("text","") or p.get("query","")
        target = p.get("to","Spanish")
        source = p.get("from","auto-detect")
        if not text: return self._fail("text to translate required")
        prompt = f"""Translate the following text from {source} to {target}.
Preserve tone, formatting, and cultural context. Return ONLY the translation.

Text: {text[:4000]}"""
        translated = await self._ai(prompt, tokens=2000)
        return self._ok(summary=f"🌐 {source} → {target}:\n\n{translated[:1500]}", data={"source_lang":source,"target_lang":target,"translated":translated,"original_length":len(text)})

    async def _h_detect_language(self, p):
        text = p.get("text","") or p.get("query","")
        if not text: return self._fail("text required")
        prompt = f"""Detect the language of this text. Return JSON:
{{"language":"Language Name","code":"ISO 639-1 code","confidence":"high/medium/low","script":"Latin/Cyrillic/etc","evidence":["word1","word2"]}}

Text: {text[:500]}

Return ONLY the JSON."""
        result = await self._ai(prompt, temp=0.1, tokens=300)
        return self._ok(summary=result, data={"text_sample":text[:100]})

    async def _h_localize(self, p):
        content = p.get("content","") or p.get("query","")
        region = p.get("region","Latin America")
        target_lang = p.get("language","Spanish")
        if not content: return self._fail("content required")
        prompt = f"""Localize this content for {region} in {target_lang}.
This is NOT just translation — adapt:
- Cultural references and idioms
- Date/time/number formats
- Currency and measurements
- Humor and tone
- Brand names if needed

Content: {content[:3000]}

Return the localized version with a brief list of changes made."""
        localized = await self._ai(prompt, tokens=2000)
        return self._ok(summary=localized, data={"region":region,"language":target_lang})

    async def _h_summarize_translate(self, p):
        text = p.get("text","") or p.get("query","")
        target = p.get("to","English")
        if not text: return self._fail("text required")
        prompt = f"""First, summarize this foreign text in 3-5 bullet points.
Then, translate the summary to {target}.

Text: {text[:4000]}

Format:
SUMMARY (original language):
- bullet 1
- bullet 2

TRANSLATION ({target}):
- bullet 1
- bullet 2"""
        result = await self._ai(prompt, tokens=1500)
        return self._ok(summary=result, data={"target_lang":target})

    async def _h_translate_code_comments(self, p):
        code = p.get("code","") or p.get("query","")
        target = p.get("to","English")
        if not code: return self._fail("code with comments required")
        prompt = f"""Translate all comments and docstrings in this code to {target}.
Keep the code logic unchanged. Only translate human-readable text.

Code:
{code[:3000]}

Return the complete code with translated comments."""
        translated = await self._ai(prompt, tokens=2000)
        return self._ok(summary=f"Translated code comments to {target}:\n\n```\n{translated[:1500]}\n```", data={"target_lang":target})

    async def _h_language_list(self, p):
        langs = """Supported language codes (ISO 639-1):
ar Arabic | zh Chinese | nl Dutch | en English | fr French | de German
hi Hindi | id Indonesian | it Italian | ja Japanese | ko Korean
ms Malay | pt Portuguese | ru Russian | es Spanish | sw Swahili
th Thai | tr Turkish | vi Vietnamese | he Hebrew | pl Polish
ro Romanian | sv Swedish | da Danish | fi Finnish | no Norwegian
cs Czech | hu Hungarian | el Greek | bg Bulgarian | uk Ukrainian

Use these codes with 'from' and 'to' parameters."""
        return self._ok(summary=langs, data={"languages":{l.split()[0]:l.split()[1] for l in langs.split('\n') if l.strip()}})
