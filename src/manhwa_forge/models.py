"""Domain models for manhwa-forge."""
from pydantic import BaseModel, Field


class CharacterSheet(BaseModel):
    """Visual reference for a character. Injected verbatim into every panel
    the character appears in, which keeps their look consistent across the chapter."""
    name: str = Field(description="Short name used to reference the character in panels.")
    visual: str = Field(
        description=(
            "Dense physical description — age, build, hair, eyes, outfit, distinguishing marks. "
            "Write it like a casting sheet: specific, visual, repeatable."
        )
    )
    role: str | None = Field(default=None, description="e.g. 'protagonist', 'antagonist', 'ally'")


class PanelBeat(BaseModel):
    """One panel in the chapter script."""
    idx: int
    scene: str = Field(
        default="",
        description=(
            "Short scene label (e.g. 'apartment-night', 'rooftop-chase'). Panels sharing a scene "
            "should share setting; scene change is a strong signal to open with an establishing shot."
        ),
    )
    description: str = Field(description="Visual description of what's in the panel")
    characters_in_panel: list[str] = Field(
        default_factory=list,
        description="Names from ChapterScript.characters that appear visibly in this panel.",
    )
    dialogue: str | None = Field(default=None, description="Speech-bubble text, or None")
    speaker: str | None = Field(default=None, description="Which character is speaking (by name)")
    caption: str | None = Field(default=None, description="Narration caption text, or None")
    framing: str = Field(default="medium shot", description="e.g. 'wide establishing', 'close-up', 'medium shot'")
    mood: str = Field(default="neutral", description="e.g. 'tense', 'melancholic', 'action-packed'")


class ChapterScript(BaseModel):
    """Full chapter breakdown."""
    title: str
    synopsis: str
    style: str = Field(description="Art-style keywords, e.g. 'modern webtoon, cel-shaded, color'")
    characters: list[CharacterSheet] = Field(
        default_factory=list,
        description="All named characters appearing in the chapter, with visual reference sheets.",
    )
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


# Characters the LLM might mention but shouldn't be drawn (internal monologue
# voice, narrators, etc.). Panel builders skip these when injecting visuals.
META_CHARACTER_NAMES: set[str] = {"narrator", "voiceover", "internal monologue"}
