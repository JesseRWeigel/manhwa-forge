"""Basic tests — no network, no GPU."""
from manhwa_forge.models import CharacterSheet, ChapterScript, PanelBeat
from manhwa_forge.prompts import build_panel_prompt, size_for_framing
from manhwa_forge.story import _extract_json


def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_fence():
    text = '```json\n{"a": 1, "b": [2, 3]}\n```'
    assert _extract_json(text) == {"a": 1, "b": [2, 3]}


def test_extract_json_with_preamble():
    text = 'Here is the chapter:\n{"title": "X", "panels": []}'
    out = _extract_json(text)
    assert out["title"] == "X"


def test_panel_prompt_builds():
    script = ChapterScript(
        title="T",
        synopsis="S",
        style="modern webtoon, cel-shaded color",
        panels=[],
    )
    beat = PanelBeat(
        idx=0,
        description="A man stands in the rain.",
        dialogue="I won't give up.",
        framing="medium shot",
        mood="tense",
    )
    prompt = build_panel_prompt(beat, script)
    assert "medium shot" in prompt
    assert "I won't give up." in prompt
    assert "cel-shad" in prompt
    # mood-to-lighting
    assert "shadows" in prompt or "rim lighting" in prompt


def test_size_for_framing():
    h, w = size_for_framing("wide establishing")
    assert (h, w) == (848, 1264)
    h, w = size_for_framing("close-up")
    assert (h, w) == (1264, 848)
    h, w = size_for_framing("medium shot")
    assert (h, w) == (1376, 768)


def test_character_visual_injected_into_prompt():
    script = ChapterScript(
        title="T",
        synopsis="S",
        style="modern webtoon",
        characters=[
            CharacterSheet(
                name="Mira",
                visual="Korean woman, 22. Silver nose ring. Messy black bob.",
                role="protagonist",
            ),
            CharacterSheet(name="Unseen", visual="Should not appear in this prompt."),
        ],
        panels=[],
    )
    beat = PanelBeat(
        idx=0,
        description="She sits at a desk.",
        characters_in_panel=["Mira"],
        framing="medium shot",
        mood="tense",
    )
    prompt = build_panel_prompt(beat, script)
    assert "Silver nose ring" in prompt
    assert "Should not appear" not in prompt


def test_speaker_attribution():
    script = ChapterScript(
        title="T", synopsis="S", style="modern webtoon",
        characters=[CharacterSheet(name="Mira", visual="short description")],
        panels=[],
    )
    beat = PanelBeat(
        idx=0, description="X",
        characters_in_panel=["Mira"],
        dialogue="Hello.", speaker="Mira",
        framing="close-up", mood="neutral",
    )
    prompt = build_panel_prompt(beat, script)
    assert 'reading exactly: "Hello."' in prompt
    assert "Bubble points toward Mira" in prompt


def test_narrator_meta_character_skipped():
    """'narrator' is meta — should not get injected as a drawn character."""
    script = ChapterScript(
        title="T", synopsis="S", style="modern webtoon",
        characters=[CharacterSheet(name="narrator", visual="should not appear")],
        panels=[],
    )
    beat = PanelBeat(
        idx=0, description="empty street",
        characters_in_panel=["narrator"],
        caption="The city slept.",
        framing="wide establishing", mood="melancholic",
    )
    prompt = build_panel_prompt(beat, script)
    assert "should not appear" not in prompt
    assert "The city slept." in prompt
