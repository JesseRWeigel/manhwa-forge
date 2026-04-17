"""Domain models for manhwa-forge."""
from pydantic import BaseModel, Field


class PanelBeat(BaseModel):
    """One panel in the chapter script."""
    idx: int
    description: str = Field(description="Visual description of what's in the panel")
    dialogue: str | None = Field(default=None, description="Speech/thought bubble text, or None")
    caption: str | None = Field(default=None, description="Narration caption text, or None")
    framing: str = Field(default="medium shot", description="e.g. 'wide establishing', 'close-up', 'medium shot'")
    mood: str = Field(default="neutral", description="e.g. 'tense', 'melancholic', 'action-packed'")


class ChapterScript(BaseModel):
    """Full chapter breakdown."""
    title: str
    synopsis: str
    style: str = Field(description="Art-style keywords, e.g. 'modern webtoon, cel-shaded, color'")
    panels: list[PanelBeat]


class ChapterManifest(BaseModel):
    """Record of a generated chapter, for reproducibility."""
    script: ChapterScript
    width: int
    height: int
    seed_base: int
    image_paths: list[str]
    final_chapter_path: str
    total_elapsed_s: float
