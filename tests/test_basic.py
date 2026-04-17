"""Basic tests — no network, no GPU."""
from manhwa_forge.models import ChapterScript, PanelBeat
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
