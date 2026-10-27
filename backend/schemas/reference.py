from pydantic import BaseModel, Field


class SourceInfo(BaseModel):
    file: str
    duration_sec: float
    width: int
    height: int
    detected_aspect_ratio: str


class SceneDetail(BaseModel):
    """장면을 이미지로 다시 만들 수 있을 만큼의 시각 정보 (비주얼 모듈의 이미지 생성 기준)."""
    subject: str = ""  # 피사체·인물: 나이대, 성별, 외모, 헤어, 의상
    action: str = ""  # 행동·표정·제스처
    background: str = ""  # 장소·배경·소품
    composition: str = ""  # 구도·카메라 앵글·피사체 위치·화면 비중
    lighting: str = ""  # 조명·색감·톤
    product: str = ""  # 제품 노출 방식 (손에 듦, 클로즈업, 미노출 등)


class Segment(BaseModel):
    index: int
    start: float
    end: float
    frames: list[str] = Field(default_factory=list)  # 프로젝트 폴더 기준 상대경로
    scene: str = ""  # 장면 요약 (1~2문장)
    detail: SceneDetail = Field(default_factory=SceneDetail)  # 장면 상세
    dialogue: str = ""  # 한 줄 = 한 문장
    shot_type: str = ""
    role: str = ""
    merged_from: list[int] = Field(default_factory=list)  # 동일 대사로 병합된 원래 2초 구간 번호


class Tone(BaseModel):
    speech_level: str = ""  # 존댓말 / 반말 / 혼용
    pace: str = ""
    habits: list[str] = Field(default_factory=list)
    description: str = ""


class Persona(BaseModel):
    age: str = ""
    gender: str = ""
    character: str = ""
    credibility: str = ""


class StructurePart(BaseModel):
    role: str
    start: float
    end: float
    summary: str = ""


class Overall(BaseModel):
    tone: Tone = Field(default_factory=Tone)
    concept: str = ""
    visual_style: str = ""  # 영상 전체의 촬영 방식·색감·편집 리듬
    persona: Persona = Field(default_factory=Persona)
    structure: list[StructurePart] = Field(default_factory=list)


class ReferenceAnalysis(BaseModel):
    source: SourceInfo
    segments: list[Segment] = Field(default_factory=list)
    overall: Overall = Field(default_factory=Overall)
    mock: bool = False  # Claude 미연결 상태에서 만들어진 분석
    confirmed: bool = False
