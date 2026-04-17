"""LLM-backed story outline generator.

Pluggable: Ollama (local, default) or Anthropic (cloud). Selects based on env:
  - If ANTHROPIC_API_KEY is set, use Anthropic.
  - Else use Ollama at OLLAMA_HOST (default http://localhost:11434).

The LLM is only invoked once per chapter (small prompt, ~1K tokens out), so
cost/latency is negligible either way.
"""
from __future__ import annotations
import json
import os
import re
from typing import Protocol

from .models import ChapterScript, PanelBeat


SYSTEM_PROMPT = """You are a veteran manhwa scriptwriter. Break story ideas into
concrete, visual panel beats suitable for a single webtoon chapter.

RULES THAT MATTER MOST:

1. CHARACTER SHEETS. First, define every named character with a dense visual
   description (age, build, hair, eyes, outfit, distinguishing marks). These
   sheets get injected verbatim into every panel the character appears in — so
   the more specific the sheet, the more consistent the artwork.

2. NARRATIVE ARC. Structure the chapter in 4 beats:
   • Setup (first ~20% of panels): establish character, setting, normal world
   • Inciting incident (next ~10%): something disrupts the normal
   • Rising action (next ~45%): escalating tension, complications, reveals
   • Climax + hook (last ~25%): peak conflict + a hook that makes the reader
     want the next chapter

3. SCENE CLARITY. When a scene changes (new location or big time jump), the
   first panel of that scene MUST be a wide establishing shot. Fill the
   `scene` field with a short label like 'apartment-night' or 'rooftop-chase';
   panels sharing a scene share a label.

4. PANEL VISIBILITY. Every panel MUST list which characters are visibly in it
   via `characters_in_panel` (using the exact names from your character sheet).
   If a character speaks, set `speaker` to their name. Do not put a character
   in `characters_in_panel` if they're not drawn in that panel.

5. VARY FRAMING. Alternate between wide establishing / medium shot / close-up
   / extreme close-up. Don't do 5 close-ups in a row. A good chapter reads
   like a camera that moves between reactions and their causes.

6. EXTERNALIZE INTERNAL STATES. Feelings become visible: a clenched fist,
   rain on a window, a shattered cup, a photograph torn in half. Never
   describe a panel as "she feels sad"; instead, "she stands in the rain
   staring at a photograph".

7. DIALOGUE. Max 12 words per bubble. Use captions sparingly (every 4–5 panels
   max). The CAPTION field is for narrator/internal monologue, not dialogue.

Return ONLY valid JSON matching this schema — no preamble, no markdown fences:

{
  "title": "chapter title",
  "synopsis": "one-sentence summary",
  "style": "art-style keywords — e.g. 'modern webtoon, cel-shaded color, dramatic lighting'",
  "characters": [
    {
      "name": "Mira",
      "visual": "Korean woman, early twenties. Messy black chin-length bob, silver nose ring. Heavy dark circles under tired brown eyes. Oversized charcoal hoodie with frayed cuffs, baggy grey sweatpants. Chipped black nail polish.",
      "role": "protagonist"
    }
  ],
  "panels": [
    {
      "idx": 0,
      "scene": "apartment-night",
      "description": "what's visually in this panel (subject, setting, action, lighting, mood)",
      "characters_in_panel": ["Mira"],
      "dialogue": "speech-bubble text or null",
      "speaker": "Mira" or null,
      "caption": "narrator caption text or null",
      "framing": "wide establishing | medium shot | close-up | extreme close-up | low angle | high angle",
      "mood": "one word — tense, melancholic, hopeful, ominous, action-packed, wistful"
    }
  ]
}
"""


def _user_prompt(idea: str, n_panels: int, style_hint: str | None) -> str:
    style_line = f"\nStyle preference: {style_hint}" if style_hint else ""
    return (
        f"Story idea: {idea}\n"
        f"Target panel count: {n_panels} (allow +/- 2 for narrative breathing room){style_line}\n\n"
        f"First write the character sheets, then write the {n_panels} panels following the "
        f"4-beat arc (setup / inciting incident / rising action / climax + hook). "
        f"Return the full chapter JSON now — no preamble, no fences."
    )


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class OllamaClient:
    """Calls local Ollama. Uses keep_alive=0 to release the model after each call
    so ERNIE can reclaim VRAM immediately."""

    def __init__(self, model: str = "gemma4:26b-a4b-it-q4_K_M", host: str | None = None):
        self.model = model
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    def complete(self, system: str, user: str) -> str:
        import requests
        r = requests.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "keep_alive": 0,  # release memory immediately after
                "options": {"temperature": 0.8, "top_p": 0.95},
            },
            timeout=300,
        )
        r.raise_for_status()
        return r.json()["message"]["content"]


class AnthropicClient:
    """Calls Anthropic API. Fast, cheap for the tiny story prompt."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        try:
            import anthropic
        except ImportError as e:
            raise ImportError(
                "anthropic not installed. Install with: pip install manhwa-forge[anthropic]"
            ) from e
        self.model = model
        self._client = anthropic.Anthropic()

    def complete(self, system: str, user: str) -> str:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text


def get_default_client() -> LLMClient:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicClient()
    return OllamaClient()


_UNESCAPED_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _extract_json(text: str) -> dict:
    """Be forgiving about LLM formatting.

    Handles: markdown fences, leading/trailing prose, and unescaped control
    characters inside string values (a common Ollama quirk — models sometimes
    emit literal newlines or NBSPs inside JSON strings that would otherwise
    break the parser).
    """
    text = text.strip()
    # strip ```json ... ``` fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # find the outermost { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in LLM output:\n{text[:500]}")
    candidate = text[start : end + 1]
    # First try: strict parse.
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # Fallback 1: strict=False accepts control chars inside strings (e.g. literal \n).
    try:
        return json.loads(candidate, strict=False)
    except json.JSONDecodeError:
        pass
    # Fallback 2: scrub the unprintables entirely and retry.
    return json.loads(_UNESCAPED_CONTROL_CHARS.sub(" ", candidate))


def generate_script(
    idea: str,
    n_panels: int = 30,
    style_hint: str | None = None,
    client: LLMClient | None = None,
) -> ChapterScript:
    """Expand a one-line idea into a structured chapter script with character sheets."""
    if client is None:
        client = get_default_client()
    raw = client.complete(SYSTEM_PROMPT, _user_prompt(idea, n_panels, style_hint))
    data = _extract_json(raw)
    # coerce panel indices in case the LLM mis-numbered
    panels = [PanelBeat(**{**p, "idx": i}) for i, p in enumerate(data["panels"])]
    from .models import CharacterSheet
    characters = [CharacterSheet(**c) for c in data.get("characters", [])]
    return ChapterScript(
        title=data["title"],
        synopsis=data["synopsis"],
        style=data.get("style", "modern webtoon, cel-shaded color"),
        characters=characters,
        panels=panels,
    )
