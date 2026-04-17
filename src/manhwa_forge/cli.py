"""Click-based CLI."""
from __future__ import annotations
import json
from pathlib import Path

import click

from .pipeline import generate_chapter
from .render import ErnieClient


@click.group()
@click.version_option(package_name="manhwa-forge")
def cli() -> None:
    """manhwa-forge — story idea → full manhwa chapter."""


@cli.command()
@click.option("--idea", required=True, help="One-line story idea.")
@click.option("--panels", default=30, show_default=True, type=int, help="Number of panels.")
@click.option("--style", default=None, help="Art-style hint, e.g. 'murim cultivation, stormy palette'.")
@click.option("--out", "out_dir", default="outputs/latest", show_default=True,
              type=click.Path(path_type=Path), help="Output directory.")
@click.option("--seed", default=42, show_default=True, type=int, help="Base seed for reproducibility.")
def generate(idea: str, panels: int, style: str | None, out_dir: Path, seed: int) -> None:
    """Generate a chapter from scratch."""
    manifest = generate_chapter(
        idea=idea, out_dir=out_dir, n_panels=panels, style_hint=style, seed_base=seed,
    )
    click.secho(f"\n✓ {manifest.final_chapter_path}", fg="green")


@cli.command()
@click.option("--script", "script_path", required=True, type=click.Path(exists=True, path_type=Path),
              help="Existing script.json (skip the LLM step).")
@click.option("--out", "out_dir", default="outputs/latest", show_default=True,
              type=click.Path(path_type=Path), help="Output directory.")
@click.option("--seed", default=42, show_default=True, type=int)
def render_script(script_path: Path, out_dir: Path, seed: int) -> None:
    """Render panels + composite from an already-written script.json."""
    from .models import ChapterScript
    from .prompts import build_panel_prompt, size_for_framing
    from .layout import compose_webtoon
    import time

    script = ChapterScript.model_validate_json(script_path.read_text())
    out_dir.mkdir(parents=True, exist_ok=True)
    panels_dir = out_dir / "panels"
    panels_dir.mkdir(exist_ok=True)

    ernie = ErnieClient()
    try:
        ernie.health()
    except Exception as e:
        raise click.ClickException(f"ERNIE server unreachable: {e}")

    panel_paths = []
    t0 = time.time()
    for beat in script.panels:
        h, w = size_for_framing(beat.framing)
        prompt = build_panel_prompt(beat, script)
        p = panels_dir / f"panel_{beat.idx:02d}.png"
        t = time.time()
        ernie.generate_to_file(p, prompt=prompt, height=h, width=w, seed=seed + beat.idx)
        panel_paths.append(p)
        click.echo(f"  [{beat.idx:02d}] {time.time()-t:.1f}s")

    final = compose_webtoon(panel_paths, out_dir / "chapter.png", title=script.title)
    click.secho(f"\n✓ {final}  ({time.time()-t0:.1f}s)", fg="green")


@cli.command()
def health() -> None:
    """Ping the ERNIE server."""
    client = ErnieClient()
    try:
        h = client.health()
        click.echo(json.dumps(h, indent=2))
    except Exception as e:
        raise click.ClickException(f"ERNIE server unreachable at {client.host}: {e}")


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind address. Keep on localhost — no auth.")
@click.option("--port", default=5001, show_default=True, type=int)
def web(host: str, port: int) -> None:
    """Launch the local web UI (Flask + SSE). Install with: pip install -e '.[web]'."""
    try:
        from .web import create_app
    except ImportError as e:
        raise click.ClickException(
            f"Web UI deps missing ({e}). Install with: pip install -e '.[web]'"
        )
    app = create_app()
    click.secho(f"→ http://{host}:{port}  (Ctrl-C to stop)", fg="green")
    # debug=False is deliberate: exposing the Werkzeug debugger is a known RCE.
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    cli()
