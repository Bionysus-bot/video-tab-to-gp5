from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GraceNote(StrictModel):
    fret: int = Field(ge=0, le=36)
    duration: Literal[16, 32, 64] = 32
    on_beat: bool = False


class TabNote(StrictModel):
    string: int = Field(ge=1, le=7, description="1 is the highest pitched string")
    fret: int = Field(ge=0, le=36)
    kind: Literal["normal", "tie", "dead"] = "normal"
    slide: bool = False
    legato_slide: bool = False
    slide_out: Literal['down','up'] | None = None
    hammer: bool = False
    staccato: bool = False
    grace: GraceNote | None = None


class TabBeat(StrictModel):
    duration: Literal[1, 2, 4, 8, 16, 32, 64]
    dotted: bool = False
    triplet: bool = False
    notes: list[TabNote] = Field(default_factory=list)
    unresolved: list[Literal['pitch', 'duration']] = Field(default_factory=list)


class TabMeasure(StrictModel):
    number: int = Field(ge=1)
    numerator: int = Field(default=4, ge=1, le=32)
    denominator: Literal[1, 2, 4, 8, 16, 32] = 4
    beats: list[TabBeat]
    source: str = ""
    confidence: float = Field(default=0, ge=0, le=1)
    issues: list[str] = Field(default_factory=list)
    reviewed: bool = False


class Score(StrictModel):
    title: str = Field(default="Transcribed score", max_length=100)
    instrument: Literal["bass", "guitar"] = "bass"
    tempo: int = Field(default=120, ge=20, le=300)
    tuning: list[int] = Field(default_factory=lambda: [43, 38, 33, 28], min_length=4, max_length=7)
    settings_confirmed: bool = False
    measures: list[TabMeasure] = Field(default_factory=list)


class RecognitionConfig(StrictModel):
    strategy: Literal['hybrid', 'vision'] = 'hybrid'
    provider: Literal["ollama", "compatible"] = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model: str = ""
    max_rows: int = Field(default=3, ge=1, le=200)
    force: bool = False


class RecognitionResult(StrictModel):
    measures: list[TabMeasure]
    warnings: list[str] = Field(default_factory=list)


class RowExclusion(StrictModel):
    excluded: bool
    reason: str = Field(default='',max_length=300)
