"""모듈 간 데이터 계약.

기획 모듈 → 영상 모듈(비주얼/사운드)은 이 스키마로 직렬화된 JSON 파일로만 연결된다.
필드를 바꾸면 Script.version을 올리고 PLAN.md §5를 함께 갱신할 것.
"""
from .gate import GATE_STEP, Gate, GateKind
from .product import Product, ProductImage, ProductImages
from .production import Production, SoundAsset, SoundLine, SoundTrack, VisualAsset, VisualTrack
from .project import JobState, Project
from .reference import Overall, Persona, ReferenceAnalysis, SceneDetail, Segment, SourceInfo, StructurePart, Tone
from .script import AspectRatio, Scene, Script, ScriptMeta, Voice
