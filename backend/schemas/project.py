from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from .script import AspectRatio


class JobState(BaseModel):
    status: Literal["idle", "running", "done", "error"] = "idle"
    progress: float = 0  # 0~1
    message: str = ""
    # 진행 표시 (화면의 로딩바·남은 시간)
    started_at: float = 0  # 시작 시각 (epoch 초)
    eta_min: float | None = None  # 남은 시간 범위 (초). 정확히 알 수 없으면 최소~최대로 표시
    eta_max: float | None = None
    eta_at: float = 0  # eta를 계산한 시각 (화면이 이후 흐른 시간만큼 줄여서 보여 준다)
    done: int = 0  # 끝난 작업 수 / 전체
    total: int = 0


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
