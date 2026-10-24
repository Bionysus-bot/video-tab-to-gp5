from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.models.score import Score
from app.models.schemas import ROI


class ConversionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source: Literal['video', 'pdf', 'existing']
    input_id: str | None = None
    layout: Literal['tab', 'standard-tab']
    roi: ROI | None = None
    base_revision: str | None = None
    model: str = ''
    provider: Literal['ollama', 'compatible'] = 'ollama'
    base_url: str = 'http://127.0.0.1:11434'
    review: bool = False
    recover: bool = True
    force: bool = False
    tempo: int = Field(default=120, ge=20, le=300)
    tuning: list[int] = Field(default_factory=lambda:[43,38,33,28], min_length=4, max_length=5)
    budget_seconds: int = Field(default=600, ge=10, le=1800)

    @model_validator(mode='after')
    def valid_area(self):
        if self.roi and (min(self.roi.x,self.roi.y)<0 or min(self.roi.width,self.roi.height)<1):
            raise ValueError('选区起点不能为负，宽高必须大于零。')
        if self.tuning!=sorted(set(self.tuning),reverse=True) or any(v<0 or v>127 for v in self.tuning):
            raise ValueError('调弦需从高到低填写四或五个不同的 MIDI 音高（0–127）。')
        return self


class ScoreEdit(BaseModel):
    expected_revision: str
    score: Score


class Activation(BaseModel):
    expected_revision: str | None = None
