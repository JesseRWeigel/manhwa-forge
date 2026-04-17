"""Convert a PanelBeat into a concrete ERNIE-Image-Turbo prompt.

We lean into what ERNIE does well (text rendering, cel-shaded characters,
structured compositions) and avoid what it doesn't (multi-panel grids,
complex spatial instructions about subject positioning).

Key to character consistency across panels: the full CharacterSheet.visual
description gets injected into every panel prompt where that character
appears. Same description → similar character across panels.
"""
from __future__ import annotations
from .models import META_CHARACTER_NAMES, ChapterScript, PanelBeat


_MOOD_TO_LIGHTING = {
    "tense": "harsh contrasting shadows, dramatic rim lighting",
    "melancholic": "soft diffused light, muted palette, rain drops or fog",
    "hopeful": "warm golden hour light, gentle bloom, pastel highlights",
    "ominous": "deep cool shadows, blue-green palette, eerie glow",
    "action-packed": "motion blur, speed lines, high-contrast dynamic lighting",
    "wistful": "soft twilight purples and pinks, gentle haze",
    "neutral": "balanced natural lighting",
}


def _visible_characters(beat: PanelBeat, script: ChapterScript):
    """Return CharacterSheets for characters actually visible in the panel."""
    names = {n.lower() for n in beat.characters_in_panel if n.lower() not in META_CHARACTER_NAMES}
    return [c for c in script.characters if c.name.lower() in names]


def build_panel_prompt(beat: PanelBeat, script: ChapterScript) -> str:
    parts: list[str] = []

    # 1) Medium + format
    parts.append(
        f"A Korean manhwa panel in full color, vertical composition, {beat.framing}."
    )

    # 2) Character visuals — injected verbatim for consistency
    visible = _visible_characters(beat, script)
    if visible:
        char_lines = []
        for c in visible:
            char_lines.append(f"{c.name}: {c.visual}")
        parts.append("Characters visibly present (draw exactly as described): " + " | ".join(char_lines) + ".")

    # 3) Scene description (what's happening + setting)
    parts.append(beat.description.strip())

    # 4) Mood/lighting cues
    lighting = _MOOD_TO_LIGHTING.get(beat.mood.lower(), "balanced lighting")
    parts.append(lighting + ".")

    # 5) Dialogue — attributed to speaker if we know them
    if beat.dialogue:
        attribution = ""
        if beat.speaker:
            speaker = next((c for c in visible if c.name.lower() == beat.speaker.lower()), None)
            if speaker is not None:
                attribution = f" Bubble points toward {speaker.name}."
        parts.append(
            f'A clean white speech bubble with black outline, English text reading exactly: "{beat.dialogue}".{attribution}'
        )

    # 6) Caption — narrator box
    if beat.caption:
        parts.append(
            f'A narration caption box with dark background and white English text reading exactly: "{beat.caption}".'
        )

    # 7) Style suffix — consistent across panels
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
