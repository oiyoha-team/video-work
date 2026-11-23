"""② 영상 자동화 산출물 (data/projects/{id}/production.json)."""
from pydantic import BaseModel, Field


class VisualVersion(BaseModel):
    """다시 만들기 전 결과 (이전/새 결과를 비교해 고를 수 있게 보관)."""
    image: str | None = None
    video: str | None = None
    prompt: str = ""
    motion: str = ""
    video_prompt: str = ""
    image_approved: bool = False
    instruction: str = ""
    v: int = 0


class VisualAsset(BaseModel):
    prompt: str = ""  # 이미지 생성 프롬프트 (영어). 수정 지시를 받으면 Claude가 고쳐 쓴다
    motion: str = ""  # 이미지→영상 변환 시 카메라 움직임
    video_prompt: str = ""  # 영상 수정 지시를 반영한 영상 프롬프트 (비우면 motion으로 만든다)
    image: str | None = None  # 프로젝트 폴더 기준 상대경로
    has_person: bool = True  # 이 장면에 인물이 나오는지 (인물 기준 이미지를 넣을지)
    image_approved: bool = False  # [이미지 전체 승인] 후에만 영상화한다 (이미지를 다시 만들면 그 장면은 다시 승인 필요)
    video: str | None = None
    error: str = ""
    instruction: str = ""  # 마지막으로 반영한 수정 지시 (사용자가 입력, 한국어)
    prev: VisualVersion | None = None  # 다시 만들기 전 결과 — 사용자가 이전/새 결과 중 고를 때까지 보관
    busy: str = ""  # 진행 표시: "" | queued | image | video
    busy_since: float = 0
    v: int = 0  # 캐시 무효화용 버전


class SoundLine(BaseModel):
    """문장 하나 = 음성 파일 하나. 마음에 안 드는 문장만 다시 만들 수 있다."""
    text: str
    audio: str | None = None
    duration: float = 0
    error: str = ""
    v: int = 0


class SoundAsset(BaseModel):
    lines: list[SoundLine] = Field(default_factory=list)  # 장면 대사의 문장별 음성 (대사 없으면 빈 목록)
    duration: float = 0  # 문장 음성 길이 합계
    error: str = ""
    busy: str = ""  # "" | queued | audio
    busy_since: float = 0
    v: int = 0


class VisualTrack(BaseModel):
    engine: str = ""
    # ── 레퍼런스에서 '빌려 온' 것 (그대로 복사하지 않음) ──
    style_guide: str = ""  # 그림체·질감·색감·조명·카메라 언어 (영어, 모든 장면 공통)
    world: str = ""  # 새로 정한 배경·공간 (레퍼런스와 다른 장소, 영어)
    concept_note: str = ""  # 레퍼런스에서 가져온 것 / 새로 만든 것 요약 (화면 표시용, 한국어)
    anchor_scene: str = ""  # 기준 장면 (첫 장면). 나머지 장면은 이 이미지의 그림체·인물·세계관을 따른다
    # 레퍼런스 장면 구도 반영 정도: low(역할·샷 크기만) | medium(샷 크기·앵글·구도·동작) | high(+배경 구성 종류까지)
    # 그림체·인물·색감은 어느 단계든 레퍼런스를 복사하지 않는다
    ref_follow: str = "medium"
    character: str = ""  # 새 인물 설정 (영어)
    cast_image: str | None = None  # 인물 기준 이미지 (첫 장면에 인물이 있으면 그 장면, 없으면 첫 장면 그림체로 만든 인물)
    cast_v: int = 0
    product_scale: str = ""  # 손에 든 사진으로 읽은 제품 실제 크기 (영어)
    product_roles: dict[str, str] = Field(default_factory=dict)  # {제품 사진 경로: in_hand | packaging | other}
    image_model: str = ""  # 이미지 모델 (비우면 config 기본값). 목록은 visual/catalog.py가 12시간마다 갱신
    video_model: str = ""  # 이미지→영상 모델 (비우면 config 기본값)
    scenes: dict[str, VisualAsset] = Field(default_factory=dict)


class TTSSettings(BaseModel):
    """사용자가 5단계에서 고르는 음성 설정 (생성 시작 전에 조절)."""
    tempo: float = 1.0  # 배속 0.5 ~ 2.0
    emotion: str = "smart"  # smart(앞뒤 문맥으로 자동) | normal | happy | sad | angry | whisper | toneup | tonedown | 목소리별 특수 감정
    emotion_intensity: float = 1.0  # 0 ~ 2 (emotion이 smart가 아닐 때)
    pitch: int = 0  # 반음 단위 -12 ~ 12


class SoundTrack(BaseModel):
    engine: str = ""
    voice: str = ""  # 사용한 목소리 이름 (표시용)
    voice_id: str = ""  # 타입캐스트 목소리 ID (비우면 화자 페르소나로 자동 선택)
    settings: TTSSettings = Field(default_factory=TTSSettings)
    scenes: dict[str, SoundAsset] = Field(default_factory=dict)


class Production(BaseModel):
    visual: VisualTrack = Field(default_factory=VisualTrack)
    sound: SoundTrack = Field(default_factory=SoundTrack)
