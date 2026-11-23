"""Exercise chapter artifacts under a simulated non-UTF-8 Windows locale."""
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from manhwa_forge import cli, pipeline
from manhwa_forge.models import ChapterManifest, ChapterScript, PanelBeat


@pytest.fixture(autouse=True)
def legacy_text_encoding(monkeypatch):
    original_open = Path.open

    def open_with_legacy_default(self, mode="r", buffering=-1, encoding=None,
                                 errors=None, newline=None):
        if "b" not in mode and encoding in (None, "locale"):
            encoding = "cp1252"
        return original_open(self, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, "open", open_with_legacy_default)


@pytest.fixture
def chapter():
    return ChapterScript(
        title="Mira in 서울", synopsis="She reads 日本語.", style="webtoon",
        panels=[PanelBeat(idx=0, description="A sign that says 서울.", dialogue="こんにちは")],
    )


class FakeRenderer:
    def __init__(self):
        self.prompts = []

    def health(self):
        return {"ok": True}

    def generate_to_file(self, path, *, prompt, **_kwargs):
        self.prompts.append(prompt)
        Image.new("RGB", (80, 80)).save(path)


def test_generation_writes_utf8_script_prompts_and_manifest(tmp_path, monkeypatch, chapter):
    monkeypatch.setattr(pipeline, "generate_script", lambda *_: chapter)
    monkeypatch.setattr(pipeline, "wait_for_server", lambda *_args, **_kwargs: True)
    manifest = pipeline.generate_chapter("idea", tmp_path, ernie=FakeRenderer(), verbose=False)

    assert ChapterScript.model_validate_json((tmp_path / "script.json").read_bytes()) == chapter
    assert "こんにちは" in (tmp_path / "panels/panel_00.prompt.txt").read_bytes().decode("utf-8")
    assert ChapterManifest.model_validate_json((tmp_path / "manifest.json").read_bytes()) == manifest


def test_render_script_decodes_utf8_without_changing_dialogue(tmp_path, monkeypatch, chapter):
    renderer = FakeRenderer()
    monkeypatch.setattr(cli, "ErnieClient", lambda: renderer)
    script_path = tmp_path / "script.json"
    script_path.write_bytes(chapter.model_dump_json().encode("utf-8"))
    result = CliRunner().invoke(cli.cli, [
        "render-script", "--script", str(script_path), "--out", str(tmp_path / "out"),
    ])

    assert result.exit_code == 0, result.exception
    assert len(renderer.prompts) == 1
    assert "こんにちは" in renderer.prompts[0]


def test_web_worker_writes_utf8_artifacts(tmp_path, monkeypatch, chapter):
    pytest.importorskip("flask")
    from manhwa_forge import web

    monkeypatch.setattr(web, "ErnieClient", FakeRenderer)
    monkeypatch.setattr(web, "wait_for_server", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(web, "generate_script", lambda *_: chapter)
    job = web.Job("fixture", "idea", 1, None)
    web._run_job(job, tmp_path)

    assert job.status == "done", job.error
    assert ChapterScript.model_validate_json((tmp_path / job.id / "script.json").read_bytes()) == chapter
    assert "こんにちは" in (tmp_path / job.id / "panels/panel_00.prompt.txt").read_bytes().decode("utf-8")
