"""장면 역할/샷 타입 공통 정의 (프론트엔드 src/labels.ts와 동일하게 유지)."""

ROLES = {
    "hook": "훅",
    "problem": "문제제기",
    "empathy": "공감",
    "solution": "해결책",
    "product": "제품소개",
    "proof": "증거/후기",
    "benefit": "효과",
    "offer": "혜택/프로모션",
    "cta": "CTA",
    "other": "기타",
}

SHOT_TYPES = ["extreme-close-up", "close-up", "medium", "full", "wide", "insert", "graphic"]

# 장면 상세 항목 (schemas.SceneDetail 필드 순서와 동일)
SCENE_DETAIL = {
    "subject": "피사체·인물",
    "action": "행동·표정",
    "background": "장소·배경·소품",
    "composition": "구도·카메라 앵글",
    "lighting": "조명·색감",
    "product": "제품 노출",
}


def detail_text(detail, indent: str = "") -> str:
    """SceneDetail → 사람이 읽는 여러 줄 텍스트 (비어 있는 항목은 생략)."""
    return "\n".join(f"{indent}{label}: {getattr(detail, key)}" for key, label in SCENE_DETAIL.items() if getattr(detail, key))


def role_label(role: str) -> str:
    return ROLES.get(role, role or "-")


def fmt_time(sec: float) -> str:
    sec = max(0.0, sec)
    m, s = divmod(sec, 60)
    return f"{int(m)}:{s:04.1f}" if s % 1 else f"{int(m)}:{int(s):02d}"
