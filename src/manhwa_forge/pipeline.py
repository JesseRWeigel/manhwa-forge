"""End-to-end chapter generation pipeline."""
from __future__ import annotations
import json
import time
from pathlib import Path

from .layout import compose_webtoon
from .models import ChapterManifest, ChapterScript
from .prompts import build_panel_prompt, size_for_framing
from .render import ErnieClient, wait_for_server
from .story import generate_script, LLMClient


def generate_chapter(
    idea: str,
    out_dir: Path,
    n_panels: int = 30,
    style_hint: str | None = None,
    seed_base: int = 42,
    llm: LLMClient | None = None,
    ernie: ErnieClient | None = None,
    verbose: bool = True,
) -> ChapterManifest:
    """Full pipeline: idea → script → images → composited chapter PNG."""
    out_dir.mkdir(parents=True, exist_ok=True)
    panels_dir = out_dir / "panels"
    panels_dir.mkdir(exist_ok=True)

    if ernie is None:
        ernie = ErnieClient()
    if not wait_for_server(ernie, timeout_s=10):
        raise RuntimeError(
            f"ERNIE server not reachable at {ernie.host}. "
            "Start it with `~/Projects/ernie-image-test/start-server.sh`."
        )

    t_start = time.time()

    # Phase 1 — script
    if verbose:
        print(f"[1/3] Drafting script ({n_panels} panels)...")
    script = generate_script(idea, n_panels, style_hint, llm)
    (out_dir / "script.json").write_text(script.model_dump_json(indent=2))
    if verbose:
        print(f"      title: {script.title}")
        print(f"      style: {script.style}")

    # Phase 2 — generate each panel
    if verbose:
        print(f"[2/3] Rendering {len(script.panels)} panels via ERNIE...")
    panel_paths: list[Path] = []
    for beat in script.panels:
        h, w = size_for_framing(beat.framing)
        prompt = build_panel_prompt(beat, script)
        seed = seed_base + beat.idx
        path = panels_dir / f"panel_{beat.idx:02d}.png"
        t = time.time()
        ernie.generate_to_file(path, prompt=prompt, height=h, width=w, seed=seed)
        panel_paths.append(path)
        if verbose:
            dialogue_hint = f' "{beat.dialogue[:30]}..."' if beat.dialogue else ""
            print(f"      [{beat.idx:02d}/{len(script.panels)-1}] {beat.framing:18s} {time.time()-t:.1f}s{dialogue_hint}")
        # persist per-panel prompt for debugging/iteration
        (panels_dir / f"panel_{beat.idx:02d}.prompt.txt").write_text(prompt)

    # Phase 3 — composite
    if verbose:
        print("[3/3] Composing chapter...")
    final_path = out_dir / "chapter.png"
    compose_webtoon(panel_paths, final_path, title=script.title)

    elapsed = time.time() - t_start
    # first panel's size determines canvas width for manifest purposes
    from PIL import Image as PILImage
    first = PILImage.open(panel_paths[0])
    manifest = ChapterManifest(
        script=script,
        width=first.width,
        height=first.height,
        seed_base=seed_base,
        image_paths=[str(p) for p in panel_paths],
        final_chapter_path=str(final_path),
        total_elapsed_s=round(elapsed, 1),
    )
    (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2))
    if verbose:
        print(f"\nDone in {elapsed:.1f}s.  Chapter: {final_path}")
    return manifest
