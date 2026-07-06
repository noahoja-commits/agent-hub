"""
Image Agent — generates images using DALL-E and other APIs.

Uses OpenAI DALL-E for image generation. Requires OPENAI_API_KEY.
Also supports Stable Diffusion via Replicate as fallback.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.image")


class ImageAgent(BaseAgent):
    name = "Image Agent"
    description = "Generates images from text descriptions using AI (DALL-E)"

    def get_capabilities(self) -> dict[str, str]:
        return {
            "generate": "Generate an image from a text description",
            "generate_variations": "Generate variations of an existing image",
            "generate_logo": "Generate a logo or icon design",
            "generate_illustration": "Generate an illustration or artwork",
        }

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_handle_{action}", None)
        if not handler:
            return self._fail(f"Unknown action: {action}")
        return await handler(params)

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    async def _handle_generate(self, params: dict[str, Any]) -> dict[str, Any]:
        prompt = params.get("prompt", "") or params.get("query", "")
        size = params.get("size", "1024x1024")
        style = params.get("style", "vivid")  # vivid or natural

        if not prompt:
            return self._fail("prompt is required — describe the image you want")

        result = await self._generate_dalle(prompt, size, style)
        if result.get("url"):
            return self._ok(
                summary=f"🖼️ Generated: \"{prompt[:100]}\"\n\n![Image]({result['url']})\n\n{result['url']}",
                data=result,
            )
        return self._fail(result.get("error", "Image generation failed"))

    async def _handle_generate_variations(self, params: dict[str, Any]) -> dict[str, Any]:
        base_prompt = params.get("prompt", "") or params.get("query", "")
        count = params.get("count", 3)

        if not base_prompt:
            return self._fail("prompt is required")

        variations = []
        for i in range(min(count, 4)):
            variant_prompt = f"{base_prompt} — variation {i + 1}"
            result = await self._generate_dalle(variant_prompt, "1024x1024", "vivid")
            if result.get("url"):
                variations.append({"index": i + 1, "prompt": variant_prompt, "url": result["url"]})

        if variations:
            lines = [f"Variations of \"{base_prompt[:80]}\":"]
            for v in variations:
                lines.append(f"\n{v['index']}. {v['url']}")
            return self._ok(summary="\n".join(lines), data={"variations": variations, "base_prompt": base_prompt})
        return self._fail("Could not generate any variations")

    async def _handle_generate_logo(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "") or params.get("query", "")
        style = params.get("style", "modern minimal")

        if not name:
            return self._fail("name is required — what is the logo for?")

        prompt = f"Professional logo design for '{name}'. {style} style. Clean, scalable, memorable. No text except the brand name. Vector-style, flat design, suitable for dark and light backgrounds."
        result = await self._generate_dalle(prompt, "1024x1024", "vivid")
        if result.get("url"):
            return self._ok(
                summary=f"🎨 Logo for \"{name}\":\n\n![Logo]({result['url']})\n\n{result['url']}",
                data=result,
            )
        return self._fail(result.get("error", "Logo generation failed"))

    async def _handle_generate_illustration(self, params: dict[str, Any]) -> dict[str, Any]:
        prompt = params.get("prompt", "") or params.get("query", "")
        style = params.get("style", "digital art")

        if not prompt:
            return self._fail("prompt is required")

        full_prompt = f"Beautiful illustration: {prompt}. Style: {style}. High quality, detailed, artistic."
        result = await self._generate_dalle(full_prompt, "1024x1024", "vivid")
        if result.get("url"):
            return self._ok(
                summary=f"🎨 Illustration: \"{prompt[:80]}\"\n\n![Illustration]({result['url']})\n\n{result['url']}",
                data=result,
            )
        return self._fail(result.get("error", "Illustration generation failed"))

    # ------------------------------------------------------------------
    # DALL-E API
    # ------------------------------------------------------------------

    async def _generate_dalle(self, prompt: str, size: str = "1024x1024", style: str = "vivid") -> dict[str, Any]:
        """Generate image via DALL-E, with SVG fallback if DALL-E unavailable."""
        result = await self._try_dalle(prompt, size)
        if result.get("url"):
            return result

        # Fallback: generate SVG via GPT
        logger.info("DALL-E unavailable, falling back to SVG generation")
        return await self._generate_svg(prompt)

    async def _try_dalle(self, prompt: str, size: str) -> dict[str, Any]:
        """Generate image via OpenAI DALL-E."""
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return {"error": "OPENAI_API_KEY not set. Set it on Railway."}

        try:
            import httpx

            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "dall-e-2",
                        "prompt": prompt,
                        "n": 1,
                        "size": "1024x1024",
                    },
                )

                if resp.status_code == 200:
                    data = resp.json()
                    image_url = data.get("data", [{}])[0].get("url", "")
                    revised_prompt = data.get("data", [{}])[0].get("revised_prompt", prompt)
                    return {
                        "url": image_url,
                        "prompt": prompt,
                        "revised_prompt": revised_prompt,
                        "size": size,
                    }
                else:
                    error = resp.json().get("error", {}).get("message", resp.text)
                    logger.warning("DALL-E error: %s", error[:200])
                    return {"error": f"DALL-E error: {error[:200]}"}

        except Exception as exc:
            logger.warning("DALL-E request failed: %s", exc)
            return {"error": f"Image generation failed: {exc}"}

    async def _generate_svg(self, prompt: str) -> dict[str, Any]:
        """Generate an SVG image using GPT as fallback."""
        try:
            import litellm
            svg_prompt = f"""Create a simple, beautiful SVG image based on this description: "{prompt}"

Requirements:
- Valid SVG code only (no explanations)
- Use viewBox, clean shapes, gradients if appropriate
- Responsive, max 800x600
- Modern, visually appealing design
- Include descriptive alt text as an SVG comment

Return ONLY the SVG code starting with <svg>."""
            response = litellm.completion(
                model=os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
                messages=[{"role": "user", "content": svg_prompt}],
                temperature=0.7, max_tokens=1500,
            )
            svg = response.choices[0].message.content.strip()
            if "<svg" not in svg:
                start = svg.find("<svg")
                end = svg.rfind("</svg>") + 6
                if start >= 0 and end > start:
                    svg = svg[start:end]
                else:
                    return {"error": "Could not generate valid SVG"}

            # Encode as data URL
            import base64
            encoded = base64.b64encode(svg.encode()).decode()
            data_url = f"data:image/svg+xml;base64,{encoded}"

            return {
                "url": data_url,
                "prompt": prompt,
                "type": "svg",
                "svg_code": svg[:2000],
            }
        except Exception as exc:
            return {"error": f"SVG generation failed: {exc}"}
