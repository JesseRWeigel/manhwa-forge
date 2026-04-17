"""Convert a PanelBeat into a concrete ERNIE-Image-Turbo prompt.

We lean into what ERNIE does well (text rendering, cel-shaded characters,
structured compositions) and avoid what it doesn't (multi-panel grids,
complex spatial instructions about subject positioning).
"""
from __future__ import annotations
from .models import ChapterScript, PanelBeat

# A manhwa panel has: subject, action, setting, framing, mood, (maybe) text.
# We build a prompt that's dense on visual nouns + verbs, then suffix the style.


def build_panel_prompt(beat: PanelBeat, script: ChapterScript) -> str:
    parts: list[str] = []

    # 1) Medium + format
    parts.append(
        f"A Korean manhwa panel in full color, vertical composition, {beat.framing}."
    )

    # 2) Subject + action + setting (the beat description is already visual-first)
    parts.append(beat.description.strip())

    # 3) Mood/lighting cues
    mood_to_lighting = {
        "tense": "harsh contrasting shadows, dramatic rim lighting",
        "melancholic": "soft diffused light, muted palette, rain drops or fog",
        "hopeful": "warm golden hour light, gentle bloom, pastel highlights",
        "ominous": "deep cool shadows, blue-green palette, eerie glow",
        "action-packed": "motion blur, speed lines, high-contrast dynamic lighting",
        "wistful": "soft twilight purples and pinks, gentle haze",
        "neutral": "balanced natural lighting",
    }
    lighting = mood_to_lighting.get(beat.mood.lower(), "balanced lighting")
    parts.append(lighting + ".")

    # 4) Text elements (let ERNIE render these inside the image)
    if beat.dialogue:
        # Force English rendering explicitly — ERNIE's prompt enhancer will
        # otherwise localize to Japanese/Chinese when the scene looks Asian.
        parts.append(
            f"A clean white speech bubble in English reads exactly: \"{beat.dialogue}\"."
        )
    if beat.caption:
        parts.append(
            f"A narration caption box at the bottom in English reads exactly: \"{beat.caption}\"."
        )

    # 5) Style suffix — keep consistent across panels for visual coherence
    parts.append(
        f"Art style: {script.style}. "
        f"Sharp cel-shading, thick digital linework, clean outlines, professional webtoon quality."
    )

    return " ".join(parts)


# Preferred ERNIE resolutions for webtoon vertical panels.
PANEL_SIZES = {
    "tall": (1376, 768),     # very tall, mobile webtoon scroll
    "portrait": (1264, 848), # standard vertical
    "square": (1024, 1024),  # flexible
    "wide": (848, 1264),     # wider aspect (used as landscape/establishing)
}


def size_for_framing(framing: str) -> tuple[int, int]:
    """Pick a (height, width) ERNIE-allowed size based on camera framing."""
    f = framing.lower()
    if "wide" in f or "establishing" in f:
        return PANEL_SIZES["wide"]
    if "close" in f:
        return PANEL_SIZES["portrait"]
    return PANEL_SIZES["tall"]
