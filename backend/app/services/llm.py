import json
import logging
import re

import httpx
from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a cinematic prompt editor for a text-to-video model. Rewrite the user idea as one concise paragraph. Specify subject action, environment, camera shot and movement, lighting, composition, lens feeling, temporal consistency, and cinematic style. Preserve intent. Do not add text, logos, cuts, dialogue, or explanations. Output only the enhanced prompt."""
SHOT_PLANNER_PROMPT = """You are planning consecutive five-second shots for one coherent AI-generated video. Return only a JSON array of strings, with exactly the requested number of items. Every item must be a self-contained text-to-video prompt that repeats the same subject identity, clothing, environment, lighting, palette, and visual style. Progress one simple action naturally from shot to shot. Use compatible framing at shot boundaries. Do not add dialogue, titles, logos, captions, scene changes, explanations, or markdown."""


def _fallback_shots(prompt: str, count: int) -> list[str]:
    stages = ["opening", "early continuation", "middle continuation", "later continuation", "closing", "final closing"]
    return [
        (
            f"{prompt}. This is the {stages[min(index, len(stages) - 1)]} shot of one continuous sequence. "
            "Keep the exact same subject appearance, clothing, environment, lighting, color palette, lens character, "
            "screen direction, and cinematic style. Show one simple natural progression of the action, with no cut, "
            "dialogue, text, logo, or scene change."
        )
        for index in range(count)
    ]


async def plan_shots(prompt: str, count: int) -> list[str]:
    """Turn one user idea into consistent, independently renderable shot prompts."""
    fallback = _fallback_shots(prompt, count)
    if settings.llm_provider == "disabled":
        return fallback
    user_prompt = f"Create exactly {count} consecutive shots for this idea:\n{prompt}"
    try:
        if settings.llm_provider == "ollama":
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{settings.ollama_url.rstrip('/')}/api/chat",
                    json={
                        "model": settings.ollama_model,
                        "stream": False,
                        "keep_alive": 0,
                        "format": "json",
                        "messages": [
                            {"role": "system", "content": SHOT_PLANNER_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "options": {"temperature": 0.25, "num_predict": min(1400, count * 220)},
                    },
                )
                response.raise_for_status()
                raw = response.json()["message"]["content"].strip()
        else:
            if not settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            response = await client.chat.completions.create(
                model=settings.openai_model,
                temperature=0.25,
                messages=[
                    {"role": "system", "content": SHOT_PLANNER_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = (response.choices[0].message.content or "").strip()

        match = re.search(r"\[[\s\S]*\]", raw)
        parsed = json.loads(match.group(0) if match else raw)
        if isinstance(parsed, dict):
            parsed = parsed.get("shots") or parsed.get("prompts")
        if not isinstance(parsed, list) or len(parsed) != count:
            raise ValueError("Shot planner returned the wrong number of shots")
        shots = [str(item).strip()[:4000] for item in parsed]
        if any(len(item) < 20 for item in shots):
            raise ValueError("Shot planner returned an incomplete prompt")
        return shots
    except Exception:
        logger.exception("Shot planning failed; using continuity-preserving fallback prompts")
        return fallback




async def expand_prompt(prompt: str) -> str:
    if settings.llm_provider == "disabled":
        return prompt
    try:
        if settings.llm_provider == "ollama":
            async with httpx.AsyncClient(timeout=90) as client:
                response = await client.post(
                    f"{settings.ollama_url.rstrip('/')}/api/chat",
                    json={
                        "model": settings.ollama_model,
                        "stream": False,
                        "keep_alive": 0,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                        "options": {"temperature": 0.55, "num_predict": 220},
                    },
                )
                response.raise_for_status()
                expanded = response.json()["message"]["content"].strip()
        else:
            if not settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            response = await client.chat.completions.create(
                model=settings.openai_model,
                temperature=0.55,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            expanded = (response.choices[0].message.content or "").strip()
        if not expanded:
            raise RuntimeError("Prompt enhancer returned an empty response")
        return expanded[:4000]
    except Exception:
        logger.exception("Prompt expansion failed; falling back to the original prompt")
        return prompt

