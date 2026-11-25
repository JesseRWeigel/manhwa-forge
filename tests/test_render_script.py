"""Exercise saved-script rendering via the CLI without calling a provider."""
import json

import pytest
from click.testing import CliRunner
from PIL import Image

from manhwa_forge import cli


def invoke_render(tmp_path, ids):
    script = tmp_path / "script.json"
    script.write_text(json.dumps({
        "title": "Fixture",
        "synopsis": "A script.",
        "style": "ink",
        "panels": [{"idx": idx, "description": f"Panel {i}"} for i, idx in enumerate(ids)],
    }), encoding="utf-8")
    out = tmp_path / "new-render"
    result = CliRunner().invoke(cli.cli, ["render-script", "--script", str(script), "--out", str(out)])
    return result, out


@pytest.mark.parametrize(("ids", "error"), [
    ([], "Script must contain at least one panel"),
    ([4, 4], "Duplicate panel index: 4"),
])
def test_invalid_saved_script_cannot_start_rendering(tmp_path, monkeypatch, ids, error):
    def unavailable():
        pytest.fail("Invalid script must not initialize the renderer")

    monkeypatch.setattr(cli, "ErnieClient", unavailable)
    result, out = invoke_render(tmp_path, ids)

    assert result.exit_code == 1
    assert error in result.output
    assert not out.exists()


def test_unique_saved_panel_ids_keep_their_filenames_and_seeds(tmp_path, monkeypatch):
    rendered = []

    class Renderer:
        def health(self):
            return {}

        def generate_to_file(self, path, *, prompt, height, width, seed):
            rendered.append((path.name, seed))
            Image.new("RGB", (8, 8)).save(path)

    monkeypatch.setattr(cli, "ErnieClient", Renderer)
    result, out = invoke_render(tmp_path, [4, 7])

    assert result.exit_code == 0, result.output
    assert rendered == [("panel_04.png", 46), ("panel_07.png", 49)]
    assert (out / "chapter.png").is_file()
