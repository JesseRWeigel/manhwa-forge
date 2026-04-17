"""Heal gemma4's raw output into a valid ChapterScript.

Fixes observed:
  1. 'srole' typo  -> 'role'
  2. Raw tab characters inside a field name:  "dialog\\t\\t\\t\\t: null  ->  "dialogue": null
  3. Rogue leading slash on a key:  /speaker": null  ->  "speaker": null
  4. Truncated final panel (idx 16 cut mid-description)  -> drop the partial panel

Produces: outputs/ollama-test/script.json
"""
from __future__ import annotations
import json
import re
from pathlib import Path

from manhwa_forge.models import ChapterScript, PanelBeat, CharacterSheet


OUT_DIR = Path("/home/jesse/Projects/manhwa-forge/outputs/ollama-test")
RAW = OUT_DIR / "raw_llm_output.txt"


def heal(text: str) -> str:
    # 1) srole -> role  (typo inside character entry)
    text = text.replace('"srole"', '"role"')

    # 2) raw tab chars inside keys — collapse any tab runs to nothing, and fix
    #    the specific "dialog<tabs>: null" glitch we observed
    text = re.sub(r'"dialog\t+\s*:', '"dialogue":', text)

    # 3) rogue leading slash on a key (/speaker" -> "speaker")
    text = re.sub(r'/([a-z_]+)"\s*:', r'"\1":', text)

    # 4) strip any other stray control chars (tabs, vertical tabs) left inside strings
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    # normalise remaining tabs to spaces (tabs are *illegal* inside JSON strings)
    text = text.replace("\t", " ")

    return text


def main() -> int:
    raw = RAW.read_text()
    healed = heal(raw)

    # Find outermost { ... }
    start = healed.find("{")
    end = healed.rfind("}")
    # End may actually be the outer '}' for the partial output — but the tail was
    # truncated, so we need to rebuild a valid JSON by trimming to the last
    # *complete* panel.
    # Easier: split at "panels" array and truncate panels to whole items.
    pre, _sep, rest = healed.partition('"panels":')
    # rest begins with '[' and lists items {...},{...},...
    # find opening [
    arr_start = rest.find("[")
    # walk forward, tracking brace depth, and record end positions of each
    # complete panel (i.e. when a '}' at depth 1 closes a {)
    depth_brace = 0
    depth_bracket = 0
    last_complete = None
    i = arr_start
    in_string = False
    escape = False
    while i < len(rest):
        c = rest[i]
        if in_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
        else:
            if c == '"':
                in_string = True
            elif c == "[":
                depth_bracket += 1
            elif c == "]":
                depth_bracket -= 1
                if depth_bracket == 0:
                    last_complete = i
                    break
            elif c == "{":
                depth_brace += 1
            elif c == "}":
                depth_brace -= 1
                if depth_brace == 0 and depth_bracket == 1:
                    # end of one panel
                    last_complete = i  # position of this '}'
        i += 1

    if last_complete is None:
        raise RuntimeError("Could not locate any complete panel in healed text")

    # Rebuild: pre + "panels": + [ ... panels[0..last_complete] ] }
    truncated_array = rest[arr_start : last_complete + 1]
    # If we stopped at a panel closer (not ']'), we need to close the array + object
    if truncated_array.rstrip().endswith("}"):
        truncated_array = truncated_array + "]"
    rebuilt = pre + '"panels": ' + truncated_array + "}"

    # Sanity parse
    data = json.loads(rebuilt)
    # Re-index panels in case any gaps
    panels = [PanelBeat(**{**p, "idx": i}) for i, p in enumerate(data["panels"])]
    characters = [CharacterSheet(**c) for c in data.get("characters", [])]
    script = ChapterScript(
        title=data["title"],
        synopsis=data["synopsis"],
        style=data.get("style", "warm slice-of-life manhwa"),
        characters=characters,
        panels=panels,
    )

    (OUT_DIR / "script.json").write_text(script.model_dump_json(indent=2))

    # Round-trip check
    reloaded = ChapterScript.model_validate_json((OUT_DIR / "script.json").read_text())
    assert reloaded.title == script.title

    n_characters = len(reloaded.characters)
    n_panels = len(reloaded.panels)
    unique_scenes = {p.scene for p in reloaded.panels if p.scene}
    n_dialogue = sum(1 for p in reloaded.panels if p.dialogue)

    print(f"HEALED -> outputs/ollama-test/script.json")
    print(f"Title: {reloaded.title}")
    print(f"Characters: {n_characters}")
    for c in reloaded.characters:
        print(f"  - {c.name} ({c.role}): {c.visual[:100]}…")
    print(f"Panels: {n_panels}")
    print(f"Unique scenes: {len(unique_scenes)} -> {sorted(unique_scenes)}")
    print(f"Panels with dialogue: {n_dialogue}")
    print("\nSample panels:")
    for i in [0, n_panels // 2, n_panels - 1]:
        p = reloaded.panels[i]
        print(f"  [{p.idx}] ({p.framing} | {p.scene} | {p.mood})")
        print(f"      {p.description}")
        if p.dialogue:
            print(f"      dialogue ({p.speaker}): {p.dialogue}")

    assert any(c.visual.strip() for c in reloaded.characters), "no character visual"
    print(f"\nAssertion A (char visual): PASS")
    if n_panels >= 20:
        print(f"Assertion B (>=20 panels): PASS ({n_panels})")
    else:
        print(f"Assertion B (>=20 panels): FAIL — only {n_panels}")
    if len(unique_scenes) >= 2:
        print(f"Assertion C (>=2 scenes): PASS ({len(unique_scenes)})")
    else:
        print(f"Assertion C (>=2 scenes): FAIL — only {len(unique_scenes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
