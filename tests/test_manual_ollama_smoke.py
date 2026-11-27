import os
from pathlib import Path
from runpy import run_path


def test_importing_manual_ollama_smoke_does_not_write_or_change_environment(monkeypatch):
    smoke = Path(__file__).resolve().parents[1] / "scripts" / "test_ollama_script.py"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-not-a-real-key")
    mkdir = Path.mkdir

    def guard_output(path, *args, **kwargs):
        assert path.name != "ollama-test", "the manual smoke script wrote during import"
        return mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", guard_output)
    run_path(str(smoke), run_name="manual_ollama_smoke")
    assert os.environ["ANTHROPIC_API_KEY"] == "fixture-not-a-real-key"
