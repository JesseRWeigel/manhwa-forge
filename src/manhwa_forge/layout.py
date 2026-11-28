"""Assemble panel images into a final chapter.

Two output modes:
  - `webtoon`: one tall PNG scrollable top-to-bottom (standard for Tapas,
    Webtoons, Manta, Lezhin). Panels stacked vertically with a small gutter
    and subtle shadow.
  - `book`: side-by-side 2-page spread (traditional manga/manhwa paperback).

The webtoon mode is the default because that's where manhwa actually gets
read in 2026.
"""
from __future__ import annotations
from contextlib import closing
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

GUTTER_PX = 40
PAGE_BG = (248, 247, 244)  # warm off-white, eye-friendly on mobile
MAX_WIDTH = 1600  # cap width so the chapter file isn't absurdly large


def _load_images(paths: list[Path]) -> list[Image.Image]:
    return [Image.open(p).convert("RGB") for p in paths]


def compose_webtoon(
    panel_paths: list[Path],
    out_path: Path,
    title: str | None = None,
    gutter: int = GUTTER_PX,
    max_width: int = MAX_WIDTH,
) -> Path:
    """Stack panels vertically into one tall chapter image."""
    if not panel_paths:
        raise ValueError("no panels to compose")

    # Read only headers to size the canvas. Keeping all decoded panels (and
    # their resized copies) alongside the canvas is costly for long chapters.
    sizes = []
    for path in panel_paths:
        with Image.open(path) as source:
            sizes.append(source.size)
    target_w = min(max_width, max(width for width, _ in sizes))
    # A valid thin panel may round down to zero rows. Keep one row.
    heights = [max(1, height * target_w // width) for width, height in sizes]

    title_h = 140 if title else 0
    total_h = title_h + sum(heights) + gutter * (len(heights) + 1)
    with closing(Image.new("RGB", (target_w, total_h), PAGE_BG)) as canvas:
        if title:
            _draw_title(canvas, title, target_w, title_h)

        y = title_h + gutter
        for path, target_h in zip(panel_paths, heights):
            with closing(Image.open(path)) as source, closing(source.convert("RGB")) as panel:
                if panel.width != target_w:
                    with closing(panel.resize((target_w, target_h), Image.LANCZOS)) as resized:
                        canvas.paste(resized, (0, y))
                else:
                    canvas.paste(panel, (0, y))
            y += target_h + gutter

        out_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(out_path, optimize=True)
    return out_path


def _draw_title(canvas: Image.Image, title: str, width: int, height: int) -> None:
    draw = ImageDraw.Draw(canvas)
    # banner background
    draw.rectangle([(0, 0), (width, height)], fill=(30, 30, 36))
    # try to find a nice serif, fall back to default
    font = None
    for candidate in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSerif-Bold.ttf",
    ]:
        try:
            font = ImageFont.truetype(candidate, 56)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    # center
    bbox = draw.textbbox((0, 0), title, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((width - tw) // 2, (height - th) // 2 - 8),
        title,
        fill=(245, 240, 220),
        font=font,
    )


def compose_book_spread(
    panel_paths: list[Path],
    out_dir: Path,
    gutter: int = GUTTER_PX,
) -> list[Path]:
    """Arrange panels as 2-up spreads. Returns list of spread PNG paths."""
    images = _load_images(panel_paths)
    spread_paths: list[Path] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(images), 2):
        left = images[i]
        right = images[i + 1] if i + 1 < len(images) else None
        h = left.height if right is None else max(left.height, right.height)
        w = left.width + (gutter + right.width if right else 0)
        canvas = Image.new("RGB", (w, h), PAGE_BG)
        canvas.paste(left, (0, (h - left.height) // 2))
        if right is not None:
            canvas.paste(right, (left.width + gutter, (h - right.height) // 2))
        p = out_dir / f"spread_{i//2:02d}.png"
        canvas.save(p, optimize=True)
        spread_paths.append(p)
    return spread_paths
