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

Every panel must be VISUAL, not abstract. Describe what the reader sees: a
character doing something, a specific setting, lighting, a clear subject of
focus. Avoid vague internal states — externalize them (a clenched fist, a
stormy sky, smashed glass).

Return ONLY valid JSON matching this schema — no preamble, no markdown fences:

{
  "title": "chapter title",
  "synopsis": "one-sentence summary",
  "style": "art-style keywords — e.g. 'modern webtoon, cel-shaded color, dramatic lighting'",
  "panels": [
    {
      "idx": 0,
      "description": "what's visually in this panel (subject, setting, action, lighting, mood)",
      "dialogue": "speech-bubble text or null",
      "caption": "narrator caption text or null",
      "framing": "wide establishing | medium shot | close-up | extreme close-up | low angle | high angle",
      "mood": "one word — tense, melancholic, hopeful, ominous, action-packed, wistful"
    }
  ]
}

Keep dialogue short (max 12 words). Use captions sparingly (every 3–4 panels max).
Vary framing across panels for visual rhythm. Open with an establishing shot,
close with a hook.
"""


def _user_prompt(idea: str, n_panels: int, style_hint: str | None) -> str:
    style_line = f"\nStyle preference: {style_hint}" if style_hint else ""
    return (
        f"Story idea: {idea}\n"
        f"Panels: {n_panels}{style_line}\n\n"
        f"Produce the chapter JSON now."
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


def _extract_json(text: str) -> dict:
    """Be forgiving about LLM formatting — strip fences, leading prose, trailing prose."""
    text = text.strip()
    # strip ```json ... ``` fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # find the outermost { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in LLM output:\n{text[:500]}")
    return json.loads(text[start : end + 1])


def generate_script(
    idea: str,
    n_panels: int = 8,
    style_hint: str | None = None,
    client: LLMClient | None = None,
) -> ChapterScript:
    """Expand a one-line idea into a structured chapter script."""
    if client is None:
        client = get_default_client()
    raw = client.complete(SYSTEM_PROMPT, _user_prompt(idea, n_panels, style_hint))
    data = _extract_json(raw)
    # coerce panel indices in case the LLM mis-numbered
    panels = [PanelBeat(**{**p, "idx": i}) for i, p in enumerate(data["panels"])]
    return ChapterScript(
        title=data["title"],
        synopsis=data["synopsis"],
        style=data.get("style", "modern webtoon, cel-shaded color"),
        panels=panels,
    )
