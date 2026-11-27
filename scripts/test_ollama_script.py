"""End-to-end test of generate_script() via local Ollama.

Writes script.json, prints key stats, and validates the result.
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

from manhwa_forge.story import OllamaClient, generate_script
from manhwa_forge.models import ChapterScript


class LongTimeoutOllamaClient(OllamaClient):
    """Same as OllamaClient but with a longer read timeout — ERNIE is holding
    most of the 5090's VRAM, so Ollama falls back to CPU inference and a
    single chat call can easily exceed the 300s default."""

    def __init__(self, model: str, host: str | None = None, timeout: int = 1500,
                 num_predict: int = 3200):
        super().__init__(model=model, host=host)
        self.timeout = timeout
        self.num_predict = num_predict

    def complete(self, system: str, user: str) -> str:
        import requests
        r = requests.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "keep_alive": 0,
                "options": {
                    "temperature": 0.8,
                    "top_p": 0.95,
                    "num_predict": self.num_predict,
                },
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()["message"]["content"]


OUT_DIR = Path(__file__).resolve().parents[1] / "outputs" / "ollama-test"

IDEA = (
    "A retired samurai opens a ramen shop in modern Tokyo. "
    "A yakuza enforcer walks in carrying a child."
)
N_PANELS = 24
STYLE_HINT = "warm slice-of-life manhwa, autumn palette, soft noir edges"


def run_with(model_name: str) -> ChapterScript:
    client = LongTimeoutOllamaClient(model=model_name, timeout=1500)
    print(f"[{model_name}] calling Ollama (timeout=1500s)…", flush=True)
    t0 = time.time()
    try:
        script = generate_script(
            idea=IDEA,
            n_panels=N_PANELS,
            style_hint=STYLE_HINT,
            client=client,
        )
    except Exception as e:
        elapsed = time.time() - t0
        print(f"[{model_name}] FAILED after {elapsed:.1f}s: {type(e).__name__}: {e}", flush=True)
        # Capture raw output for debugging
        try:
            raw = client.complete(
                __import__("manhwa_forge.story", fromlist=["SYSTEM_PROMPT"]).SYSTEM_PROMPT,
                f"Story idea: {IDEA}\nTarget panel count: {N_PANELS}\nStyle: {STYLE_HINT}\nReturn JSON.",
            )
            (OUT_DIR / "raw_llm_output.txt").write_text(raw)
            print(f"[{model_name}] raw output saved to raw_llm_output.txt ({len(raw)} chars)")
        except Exception as e2:
            print(f"[{model_name}] could not capture raw output: {e2}")
        raise
    elapsed = time.time() - t0
    print(f"[{model_name}] OK in {elapsed:.1f}s", flush=True)
    return script, elapsed


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Primary: gemma4:26b. Fallback: qwen3.5:27b (if primary fails).
    primary = "gemma4:26b-a4b-it-q4_K_M"
    fallback = "qwen3.5:27b"

    script = None
    used = None
    elapsed = None
    try:
        script, elapsed = run_with(primary)
        used = primary
    except Exception as e:
        print(f"Primary failed; trying fallback {fallback}…", flush=True)
        # Uncomment if you want to try fallback:
        try:
            script, elapsed = run_with(fallback)
            used = fallback
        except Exception as e2:
            print(f"Fallback also failed: {e2}", flush=True)
            return 1

    # Save script.json
    script_path = OUT_DIR / "script.json"
    script_path.write_text(script.model_dump_json(indent=2))
    print(f"Saved: {script_path}", flush=True)

    # Re-load via model_validate_json to prove round-trip
    reloaded = ChapterScript.model_validate_json(script_path.read_text())
    assert reloaded.title == script.title

    # Stats
    n_characters = len(reloaded.characters)
    n_panels = len(reloaded.panels)
    unique_scenes = {p.scene for p in reloaded.panels if p.scene}
    n_dialogue = sum(1 for p in reloaded.panels if p.dialogue)

    print("\n=== RESULTS ===")
    print(f"Model used: {used}")
    print(f"Wall clock: {elapsed:.1f}s")
    print(f"Title: {reloaded.title}")
    print(f"Synopsis: {reloaded.synopsis}")
    print(f"Style: {reloaded.style}")
    print(f"Characters ({n_characters}):")
    for c in reloaded.characters:
        visual_preview = c.visual[:120].replace("\n", " ")
        print(f"  - {c.name} ({c.role}): {visual_preview}…")
    print(f"Panels: {n_panels}")
    print(f"Unique scenes: {len(unique_scenes)} -> {sorted(unique_scenes)}")
    print(f"Panels with dialogue: {n_dialogue}")

    # Example panel descriptions
    print("\n=== SAMPLE PANELS ===")
    for i in [0, n_panels // 2, n_panels - 1]:
        if 0 <= i < n_panels:
            p = reloaded.panels[i]
            print(f"\nPanel {p.idx} [{p.framing} | {p.scene} | {p.mood}]")
            print(f"  desc: {p.description}")
            if p.dialogue:
                print(f"  dialogue ({p.speaker}): {p.dialogue}")

    # Assertions
    assert any(c.visual.strip() for c in reloaded.characters), "no character has non-empty visual"
    assert n_panels >= 20, f"expected >=20 panels, got {n_panels}"
    assert len(unique_scenes) >= 2, f"expected >=2 unique scenes, got {len(unique_scenes)}: {unique_scenes}"

    print("\nAll assertions passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
