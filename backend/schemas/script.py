from typing import Literal

from pydantic import BaseModel, Field

AspectRatio = Literal["1:1", "4:5", "16:9", "9:16"]


class Scene(BaseModel):
    """기획안의 장면 = 레퍼런스 구간 하나. 기획 단계에서는 대사만 다룬다.

    화면(이미지) 정보는 레퍼런스 장면 분석(scene_analysis/scenes.json)을 ref_segment로 찾아
    영상 제작 단계에서 쓴다.
    """
    id: str
    start: float
    end: float
    role: str = ""
    dialogue: str = ""  # 한 줄 = 한 문장 → 사운드 모듈 TTS 원문
    ref_segment: int | None = None  # 대응하는 레퍼런스 구간 index


class Voice(BaseModel):
    persona: str = ""
    speech_level: str = ""
    pace: str = ""
    emotion: str = ""


class ScriptMeta(BaseModel):
    title: str = ""
    product_name: str = ""
    product_library_id: str | None = None
    reference: str = ""
    total_duration_sec: float = 0
    aspect_ratio: AspectRatio = "9:16"


class Script(BaseModel):
    version: int = 3  # 3: 대사 전용 (화면 정보는 scene_analysis로 분리)
    status: Literal["draft", "final"] = "draft"
    mock: bool = False
    meta: ScriptMeta = Field(default_factory=ScriptMeta)
    voice: Voice = Field(default_factory=Voice)
    scenes: list[Scene] = Field(default_factory=list)
