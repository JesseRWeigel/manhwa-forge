"""Exercise the story-provider boundary with synthetic chapter replies."""
import json

import pytest

from manhwa_forge.story import generate_script


class FakeStoryClient:
    def __init__(self, chapter):
        self.chapter = chapter

    def complete(self, system, user):
        return json.dumps(self.chapter)


@pytest.mark.parametrize("panel_fields", [{}, {"panels": None}, {"panels": []}, {"panels": {}}])
def test_invalid_panel_lists_fail_at_story_boundary(panel_fields):
    client = FakeStoryClient({"title": "Fixture", "synopsis": "A story.", **panel_fields})

    with pytest.raises(ValueError, match="Story provider returned no usable panel list"):
        generate_script("fixture", client=client)


def test_one_panel_is_accepted_and_renumbered_even_when_target_is_higher():
    client = FakeStoryClient({
        "title": "Fixture",
        "synopsis": "A story.",
        "panels": [{"idx": 9, "description": "A lantern turns on."}],
    })

    script = generate_script("fixture", n_panels=3, client=client)
    assert [(panel.idx, panel.description) for panel in script.panels] == [
        (0, "A lantern turns on."),
    ]


def test_empty_provider_reply_does_not_save_an_invalid_script(tmp_path, monkeypatch):
    from manhwa_forge import pipeline

    monkeypatch.setattr(pipeline, "wait_for_server", lambda *args, **kwargs: True)

    class RendererMustNotBeCalled:
        def generate_to_file(self, *args, **kwargs):
            pytest.fail("An empty script should not reach the renderer")

    client = FakeStoryClient({"title": "Fixture", "synopsis": "A story.", "panels": []})
    with pytest.raises(ValueError, match="Story provider returned no usable panel list"):
        pipeline.generate_chapter(
            "fixture", tmp_path, llm=client, ernie=RendererMustNotBeCalled(), verbose=False,
        )

    assert not (tmp_path / "script.json").exists()
    assert not (tmp_path / "chapter.png").exists()
    assert not (tmp_path / "manifest.json").exists()
