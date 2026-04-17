"""Take the first 6 panels of script.json and write script_first6.json."""
from pathlib import Path

from manhwa_forge.models import ChapterScript

OUT = Path("/home/jesse/Projects/manhwa-forge/outputs/ollama-test")
full = ChapterScript.model_validate_json((OUT / "script.json").read_text())
first6 = ChapterScript(
    title=full.title,
    synopsis=full.synopsis,
    style=full.style,
    characters=full.characters,
    panels=full.panels[:6],
)
(OUT / "script_first6.json").write_text(first6.model_dump_json(indent=2))
print(f"Wrote {OUT/'script_first6.json'} with {len(first6.panels)} panels")
