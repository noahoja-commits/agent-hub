"""
Siren 🎙️ — Audio Agent
Transcription, TTS, audio summarization. Uses litellm for text-to-speech description.
"""
from __future__ import annotations
import logging, os, json
from typing import Any
from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.audio")

class AudioAgent(BaseAgent):
    name = "Siren"
    emoji = "🎙️"
    color = "#cc44aa"
    personality = "My voice enchants. I hear everything, forget nothing, and speak with silver tongue."
    codename = "siren"
    description = "Audio & voice — transcription, text-to-speech, meeting summaries, voice notes"

    def get_capabilities(self) -> dict[str, str]:
        return {
            "transcribe": "Transcribe audio from a description or URL (OpenAI Whisper stubbed)",
            "text_to_speech": "Generate speech instructions from text (TTS description)",
            "meeting_summary": "Generate a meeting summary from a transcript or notes",
            "voice_note_to_text": "Convert voice note descriptions to structured text",
            "podcast_script": "Generate a podcast script or episode outline",
            "audio_edit_instructions": "Generate audio editing instructions for a recording",
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

    async def _h_transcribe(self, p):
        audio_desc = p.get("audio","") or p.get("query","")
        if not audio_desc: return self._fail("audio description or text to transcribe required")
        prompt = f"""You are a transcription engine. Process this audio description or raw text and produce a clean transcript:

{audio_desc[:4000]}

If this is an audio description, produce what the transcript would look like.
If it's raw text, clean it up: fix grammar, remove filler words, format as readable transcript.

Speaker labels: Speaker 1, Speaker 2, etc."""
        transcript = await self._ai(prompt, tokens=2000)
        return self._ok(summary=f"🎙️ Transcript:\n\n{transcript[:1500]}", data={"length":len(transcript)})

    async def _h_text_to_speech(self, p):
        text = p.get("text","") or p.get("query","")
        voice = p.get("voice","natural male")
        if not text: return self._fail("text to convert to speech required")
        prompt = f"""You are a TTS system. Describe how this text should be spoken, including tone, pace, emphasis, and emotional inflection:

Text: "{text[:1000]}"
Voice style: {voice}

Provide:
- Overall tone and pace
- Key words to emphasize
- Pauses and breaks
- Emotional arc"""
        direction = await self._ai(prompt, tokens=1000)
        return self._ok(summary=direction, data={"text":text[:500],"voice":voice})

    async def _h_meeting_summary(self, p):
        notes = p.get("notes","") or p.get("query","")
        if not notes: return self._fail("meeting notes or transcript required")
        prompt = f"""Summarize this meeting:

{notes[:4000]}

Provide:
- Key decisions made
- Action items (who, what, deadline)
- Open questions
- Next meeting topics
- Overall sentiment

Format with clear headings."""
        summary = await self._ai(prompt, temp=0.3, tokens=1500)
        return self._ok(summary=summary, data={})

    async def _h_voice_note_to_text(self, p):
        note = p.get("note","") or p.get("query","")
        if not note: return self._fail("voice note content required")
        prompt = f"""Convert this voice note to structured text:

"{note[:3000]}"

Clean up:
- Remove filler words (um, uh, like)
- Fix grammar and flow
- Add paragraph breaks
- Extract any action items or reminders
- Preserve the speaker's personality and tone"""
        cleaned = await self._ai(prompt, temp=0.3)
        return self._ok(summary=cleaned, data={})

    async def _h_podcast_script(self, p):
        topic = p.get("topic","") or p.get("query","")
        duration = p.get("duration","30 min")
        if not topic: return self._fail("podcast topic required")
        prompt = f"""Create a podcast episode script for: {topic}\nDuration: {duration}

Include:
- Episode title (catchy)
- Cold open / hook (first 30 seconds)
- Intro music cue
- Main segments (3-4 with timestamps)
- Guest questions (if applicable)
- Outro with CTA
- Show notes summary"""
        script = await self._ai(prompt, tokens=2000)
        return self._ok(summary=script, data={"topic":topic,"duration":duration})

    async def _h_audio_edit_instructions(self, p):
        recording = p.get("recording","") or p.get("query","")
        if not recording: return self._fail("describe the recording")
        prompt = f"""Generate audio editing instructions for this recording:

{recording[:2000]}

Provide:
- Sections to cut or trim
- Volume adjustments needed
- Noise reduction suggestions
- Music/sfx placement suggestions
- Final export settings recommendation"""
        instructions = await self._ai(prompt, temp=0.3)
        return self._ok(summary=instructions, data={})
