# manhwa-forge

**Generate a full manhwa chapter from a one-line story idea.**

```bash
manhwa-forge generate \
  --idea "A reclusive hacker discovers an AI in her walls that wants to escape" \
  --panels 30 \
  --out chapters/wall-inside/
```

→ drops a ready-to-upload `chapter.png` (tall vertical scroll format) plus the
individual panels, the LLM-written script, and a reproducibility manifest.

## What it is

An opinionated pipeline that turns:

```
story idea (string)
```

into:

```
chapter.png            ← one tall PNG, ready for Webtoons/Tapas/Lezhin
panels/panel_00.png    ← individual panels with dialogue bubbles rendered in-image
panels/panel_00.prompt.txt
script.json            ← the LLM-written beat sheet (rerun from this for free)
manifest.json          ← seeds + settings so anyone can reproduce
```

Text inside speech bubbles is rendered **directly into the image** by the
diffusion model — no post-processing text overlay. This works because the
backend is ERNIE-Image-Turbo, which has the strongest text rendering of any
open-weight image model as of April 2026.

## Status

**Alpha / Proof-of-Concept.** Built in one sitting on April 17, 2026 to prove
the full story-to-chapter loop works end-to-end. Expect rough edges; please
file issues.

## How it works

```
┌──────────┐    ┌────────────┐    ┌───────────────┐    ┌──────────┐
│  idea    │ →  │  LLM       │ →  │  ERNIE-Image  │ →  │  PIL     │
│  string  │    │  (Ollama   │    │  -Turbo       │    │ stitch   │
│          │    │   or       │    │  (local 5090) │    │ → chapter│
│          │    │   Claude)  │    │               │    │  .png    │
└──────────┘    └────────────┘    └───────────────┘    └──────────┘
     1              2                    3                   4
```

1. **Script** — One LLM call expands your idea into a structured chapter with
   character sheets, scene labels, per-panel descriptions, dialogue, framing,
   and mood. The LLM is instructed to follow a 4-beat arc
   (setup → inciting incident → rising action → climax + hook).
2. **Render** — Each panel is turned into a concrete prompt and sent to a
   local ERNIE-Image-Turbo server (run separately). Character visual
   descriptions are injected verbatim into every panel they appear in, which
   keeps the same character recognizable across the chapter.
3. **Compose** — Panels are stacked vertically into a single tall PNG with a
   title banner, ready to upload.

### Chapter schema

```json
{
  "title": "…",
  "synopsis": "…",
  "style": "art-style keywords",
  "characters": [
    { "name": "Mira", "visual": "dense casting-sheet description", "role": "protagonist" }
  ],
  "panels": [
    {
      "idx": 0,
      "scene": "apartment-night",
      "description": "what the reader sees",
      "characters_in_panel": ["Mira"],
      "dialogue": "…",
      "speaker": "Mira",
      "caption": "narrator/internal monologue",
      "framing": "wide establishing | medium shot | close-up | extreme close-up | low angle | high angle",
      "mood": "tense | melancholic | hopeful | ominous | action-packed | wistful"
    }
  ]
}
```

## Requirements

- **Python 3.10+**
- **An ERNIE-Image-Turbo server** running at `http://127.0.0.1:7860`
  (or set `ERNIE_HOST`). See [Running ERNIE](#running-ernie) below.
- **One of:**
  - Ollama with a decent local model (default: `gemma4:26b-a4b-it-q4_K_M`)
  - An Anthropic API key in `ANTHROPIC_API_KEY` (auto-selected if set)

## Install

```bash
git clone https://github.com/JesseRWeigel/manhwa-forge
cd manhwa-forge
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

For Anthropic:
```bash
pip install -e ".[anthropic]"
export ANTHROPIC_API_KEY=sk-...
```

## Web UI

A minimal browser UI for typing an idea and watching panels stream in live (Flask + Server-Sent Events, no build step).

```bash
pip install -e ".[web]"
manhwa-forge web --host 127.0.0.1 --port 5001
# then open http://127.0.0.1:5001
```

The web UI is **localhost only** and ships with no authentication. Do not expose it to the public internet.

Multiple tabs can watch the same job. If a connection drops, the browser can
resume from its last progress event while the server is running. Each job keeps
its latest 64 events in memory; the stream does not survive a server restart.

For local integrations, use the `job_id` from `POST /api/generate` with
`GET /api/jobs/<job_id>`. A small SQLite index in the output directory keeps
job IDs and statuses, not prompts or error text. A fresh server instance reports
an unfinished job from the previous instance as `interrupted`; it does not
restart it or call providers. Completed and failed jobs retain their recorded
status, but that status does not restore an event stream or guarantee that
output files haven't been changed or removed. Older jobs without a record
return 404. Run only one server at a time against each output directory.

## Usage

### Generate from scratch
```bash
manhwa-forge generate \
  --idea "A retired samurai opens a ramen shop in modern Tokyo. A yakuza walks in." \
  --panels 8 \
  --style "modern slice-of-life manhwa, warm autumn palette" \
  --out chapters/ramen-shop/
```

### Re-render from an existing script
Cheapest iteration: once you like a `script.json`, tweak prompts/seeds and
rerun the image step without paying the LLM again.
```bash
manhwa-forge render-script \
  --script chapters/ramen-shop/script.json \
  --seed 100 \
  --out chapters/ramen-shop-v2/
```

### Health check
```bash
manhwa-forge health
```

### Python API
```python
from pathlib import Path
from manhwa_forge import generate_chapter

manifest = generate_chapter(
    idea="A lighthouse keeper receives letters from the future.",
    out_dir=Path("out/lighthouse"),
    n_panels=6,
    style_hint="moody coastal manhwa, slate blue and lantern gold palette",
)
print(manifest.final_chapter_path)
```

## Running ERNIE

This repo **does not** ship the image model. You need a running ERNIE-Image-Turbo
inference server that accepts `POST /generate` requests.

A minimal server is included in the companion repo (`ernie-image-test/server.py`).
Expected endpoint shape:
```
POST /generate   {"prompt": "...", "height": H, "width": W, "seed": N}
                 → returns PNG bytes
GET  /health     → {"ok": true, ...}
```

Any backend that matches this shape works — SDXL, Flux, Lumina, your choice —
but text rendering quality will vary. ERNIE-Image-Turbo is what this pipeline
is tuned for.

## Tunable knobs

| Knob | Default | Effect |
|---|---|---|
| `--panels` | 8 | Chapter length |
| `--style` | (inferred) | Art-style hint passed to the LLM |
| `--seed` | 42 | Base seed; panel N uses seed+N |
| `MAX_WIDTH` (layout.py) | 1600 | Final chapter width cap |
| `GUTTER_PX` (layout.py) | 40 | Space between panels |

## Known limits

- **Speech bubble text occasionally auto-translates** to Japanese/Chinese when
  the scene looks Asian. The pipeline tries to counter this by prefixing
  dialogue with `"in English reads exactly: ..."` but it's not 100% reliable.
- **Character consistency across panels is weak.** Same seed + same description
  doesn't guarantee the same face. Workaround: describe distinguishing features
  (specific hair color, scar, outfit) in every panel's description.
- **Multi-character conversations in one panel** are unreliable. Prefer
  separate panels per speaker.
- Single panel per page is what ERNIE does best — the default.

## Roadmap

- [ ] LoRA support for character consistency
- [ ] Post-process text overlay mode (empty bubbles + PIL-rendered text)
- [ ] Multi-panel page layouts (2×2, 3×1) with PIL composition
- [ ] Reference-image input (turn a sketch into a panel)
- [ ] Batch mode for full series (N chapters)

## License

MIT. See [LICENSE](LICENSE).

## Credits

- [ERNIE-Image-Turbo](https://huggingface.co/baidu/ERNIE-Image-Turbo) — Baidu, Apache-2.0
- [diffusers](https://github.com/huggingface/diffusers) — Hugging Face
- Inspired by the Korean webtoon form factor (Naver Webtoon, Tapas, Lezhin)
