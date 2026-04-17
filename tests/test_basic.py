"""Basic tests — no network, no GPU."""
import pytest

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


def test_extract_json_tolerates_unescaped_control_chars():
    # Ollama sometimes emits a literal newline inside a string value.
    text = '{"title": "Hello\nworld", "panels": []}'
    out = _extract_json(text)
    assert "Hello" in out["title"] and "world" in out["title"]


def test_extract_json_tolerates_smart_quote_control_bytes():
    # Unprintable control chars mid-string (e.g. 0x1f) — strict=False accepts
    # them, so we survive without losing data.
    text = '{"title": "a\x1fb", "panels": []}'
    out = _extract_json(text)
    # either the raw control char remains (strict=False path) or it's scrubbed
    # to space — both are acceptable recoveries.
    assert out["title"] in ("a\x1fb", "a b")


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


# --- Web UI smoke tests -------------------------------------------------------

def _web_client(tmp_path):
    """Build a Flask test client with a no-op worker so tests never touch
    the LLM or ERNIE server."""
    flask = pytest.importorskip("flask")  # noqa: F841
    from manhwa_forge.web import create_app

    app = create_app(out_root=tmp_path / "out")
    # Replace the worker with a no-op so POST /api/generate returns instantly
    # and doesn't try to reach Ollama/ERNIE.
    app.config["RUN_JOB"] = lambda job, out_root: None
    app.config["TESTING"] = True
    return app.test_client()


def test_web_index_renders_form(tmp_path):
    client = _web_client(tmp_path)
    r = client.get("/")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "<textarea" in body
    assert "manhwa-forge" in body


def test_web_generate_returns_job_id(tmp_path):
    client = _web_client(tmp_path)
    r = client.post("/api/generate", json={"idea": "An AI wakes up inside a wall.", "panels": 8})
    assert r.status_code == 200
    data = r.get_json()
    assert "job_id" in data and isinstance(data["job_id"], str) and len(data["job_id"]) > 0


def test_web_generate_rejects_empty_idea(tmp_path):
    client = _web_client(tmp_path)
    r = client.post("/api/generate", json={"idea": "   "})
    assert r.status_code == 400
    assert "idea" in r.get_json()["error"]
