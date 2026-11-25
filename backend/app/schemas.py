from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TranscriptionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    text: str = Field(min_length=1)
    duration_sec: int = Field(default=0, ge=0)
    # Optional: languages already identified (e.g. by the final pass). ISO 639-1 codes.
    languages: list[str] | None = Field(default=None, max_length=10)


class TranscriptionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    text: str | None = Field(default=None, min_length=1)


class TranscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    text: str
    languages: list[str]
    duration_sec: int
    created_at: datetime
    updated_at: datetime


class TranscriptionPage(BaseModel):
    items: list[TranscriptionOut]
    total: int
    page: int
    page_size: int
