from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from .script import AspectRatio


class JobState(BaseModel):
    status: Literal["idle", "running", "done", "error"] = "idle"
    progress: float = 0  # 0~1
    message: str = ""


class Project(BaseModel):
    id: str
    name: str
    created_at: str
    updated_at: str
    step: int = 1  # 진입 가능한 가장 높은 단계 (1~6)
    completed: bool = False  # 영상 제작 확정 → 결과물 다운로드 가능
    aspect_ratio: AspectRatio | None = None  # None이면 레퍼런스 자동 감지값 사용
    analysis_job: JobState = Field(default_factory=JobState)
    script_job: JobState = Field(default_factory=JobState)
    visual_job: JobState = Field(default_factory=JobState)
    sound_job: JobState = Field(default_factory=JobState)

    JOB_FIELDS: ClassVar[tuple[str, ...]] = ("analysis_job", "script_job", "visual_job", "sound_job")
