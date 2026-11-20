"""Offline checks for chapter export with deterministic, tiny panel images."""

from PIL import Image

from manhwa_forge.layout import PAGE_BG, compose_webtoon


def test_webtoon_downscales_a_thin_panel_without_discarding_it(tmp_path):
    panel = tmp_path / "thin.png"
    Image.new("RGB", (32, 1), (255, 0, 0)).save(panel)
    result = compose_webtoon(
        [panel], tmp_path / "chapter.png", gutter=2, max_width=4
    )
    with Image.open(result) as chapter:
        assert chapter.size == (4, 5)
        assert chapter.getpixel((0, 2)) == (255, 0, 0)
        assert chapter.getpixel((0, 1)) == PAGE_BG
        assert chapter.getpixel((0, 3)) == PAGE_BG


def test_webtoon_keeps_proportional_height_and_panel_order(tmp_path):
    first, second = tmp_path / "red.png", tmp_path / "blue.png"
    Image.new("RGB", (8, 4), (255, 0, 0)).save(first)
    Image.new("RGB", (2, 3), (0, 0, 255)).save(second)
    result = compose_webtoon(
        [first, second], tmp_path / "chapter.png", gutter=1, max_width=4
    )
    with Image.open(result) as chapter:
        assert chapter.size == (4, 11)
        assert chapter.getpixel((0, 1)) == (255, 0, 0)
        assert chapter.getpixel((0, 3)) == PAGE_BG
        assert chapter.getpixel((0, 4)) == (0, 0, 255)
