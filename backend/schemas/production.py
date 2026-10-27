"""② 영상 자동화 산출물 (data/projects/{id}/production.json)."""
from pydantic import BaseModel, Field


class VisualAsset(BaseModel):
    prompt: str = ""  # 이미지 생성 프롬프트 (장면 분석 + 자사 대사 + 제품 이미지 기반, 영어)
    motion: str = ""  # 이미지→영상 변환 시 카메라 움직임
    image: str | None = None  # 프로젝트 폴더 기준 상대경로
    video: str | None = None
    error: str = ""
    v: int = 0  # 캐시 무효화용 버전


class SoundLine(BaseModel):
    """문장 하나 = 음성 파일 하나."""
    text: str
    audio: str | None = None
    duration: float = 0


class SoundAsset(BaseModel):
    lines: list[SoundLine] = Field(default_factory=list)  # 장면 대사의 문장별 음성 (대사 없으면 빈 목록)
    duration: float = 0  # 문장 음성 길이 합계
    error: str = ""
    v: int = 0


class VisualTrack(BaseModel):
    engine: str = ""
    scenes: dict[str, VisualAsset] = Field(default_factory=dict)


class SoundTrack(BaseModel):
    engine: str = ""
    voice: str = ""
    scenes: dict[str, SoundAsset] = Field(default_factory=dict)


class Production(BaseModel):
    visual: VisualTrack = Field(default_factory=VisualTrack)
    sound: SoundTrack = Field(default_factory=SoundTrack)
