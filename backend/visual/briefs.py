"""장면별 이미지 브리프(프롬프트·카메라 움직임)를 영상 제작 단계에서 만든다.

레퍼런스는 '복사할 원본'이 아니라 '참고 자료'다.
- 빌려 오는 것: 그림체·매체(실사 UGC / 3D 애니메이션 / 일러스트 …), 질감·색감·조명 분위기, 카메라 언어,
  화자 페르소나, 컨셉, 후킹 방식, 전개 구성(장면마다 맡은 역할), 편집 리듬.
- 새로 만드는 것: 인물(얼굴·헤어·의상), 배경·공간(world), 소품, 각 장면의 구체적인 구도.
  → 레퍼런스와 같은 장면·같은 인물·같은 의상·같은 배경이 나오지 않는다.

이미지는 첫 장면(기준 장면)을 먼저 만들고, 나머지 장면은 그 기준 장면 + 제품 사진을 참고해 일관되게 만든다
(pipeline.py). 수정 지시를 받으면 revise_image_prompt / revise_video_prompt 로 그 장면 프롬프트만 고친다.
"""
from dataclasses import dataclass, field
from pathlib import Path

from llm import claude_client
from llm.claude_client import strict_object
from planning import store
from planning.text import split_sentences

# 제품 사진 역할
ROLE_HAND = "in_hand"  # 실제 손에 들고 찍은 사진 → 실제 크기 기준
ROLE_PACKAGING = "packaging"  # 패키지 정면·누끼 → 외형 기준
ROLE_OTHER = "other"

BRIEF_SYSTEM = """당신은 숏폼 광고의 크리에이티브 디렉터 겸 아트 디렉터입니다.
레퍼런스 영상의 분석 결과와, 자사 제품으로 새로 쓴 대사, 자사 제품 정보·사진을 받습니다.
목표: 레퍼런스를 '복사'하지 않고 '참고'해서, 같은 느낌의 완전히 새로운 광고 영상을 설계합니다.

[레퍼런스에서 빌려 오는 것 — 추상적인 특징만]
- 그림체·매체: 실사 스마트폰 UGC인지, 3D 애니메이션인지, 2D 일러스트인지, 스톱모션인지 등과 그 렌더링 특징
  (선·질감·피부 표현·과장 정도), 색감 팔레트, 조명 분위기, 화질 느낌.
- 카메라 언어: 샷 크기의 리듬, 앵글 습관, 핸드헬드/고정, 셀카 구도 여부.
- 화자 페르소나(나이대·성별·성격·말투에서 드러나는 캐릭터), 컨셉, 후킹 방식(첫 장면이 시선을 끄는 방법),
  전개 구성(장면마다 맡은 역할: 후킹 → 문제 → 해결 → 증거 → 구매 유도 등).

[절대 그대로 가져오지 않는 것]
- 레퍼런스의 인물(얼굴·헤어·의상·액세서리), 인테리어·소품의 디자인, 색감, 화면 속 글자·로고.
  레퍼런스 장면을 그대로 묘사하듯 쓰면 안 된다. (장면 구도를 얼마나 따를지는 맨 위 [장면 구성] 지시를 따른다)
- 스튜디오·작가·브랜드 이름(예: 디즈니, 픽사, 지브리)을 쓰지 말고 그 그림체의 특징을 말로 풀어 쓴다.

[컷 다양성]
- 인접한 장면끼리 샷 크기·앵글이 반복되지 않게 다양하게 짠다 (익스트림 클로즈업, 클로즈업, 미디엄, 와이드, 탑뷰, 로우앵글,
  오버숄더, POV, 손·제품 인서트 등). 레퍼런스의 컷 리듬(샷 크기 변화)을 따른다.
- 모든 장면이 같은 장소의 같은 각도가 되지 않게, world 안에서 장면마다 다른 위치·방향·거리를 쓴다.
- 각 장면 prompt는 샷 크기와 카메라 앵글로 시작한다 (예: "Extreme close-up, low angle: ...").

[출력]
- style_guide (영어): 모든 장면 공통의 그림체·매체·렌더링·질감·색감·조명·카메라 느낌을 아주 구체적으로.
  예: "Stylized 3D animated feature-film look: soft rounded character shapes, big expressive eyes, subsurface-scattered skin,
  saturated warm palette, soft global illumination, shallow depth of field, cinematic 9:16 framing."
- world (영어): 이번 영상의 새 배경·공간 설정. 레퍼런스와 다른 장소·인테리어·소품·시간대로 정하되 컨셉에 맞게.
- character (영어): 새 인물. 레퍼런스 화자와 성별·연령대·페르소나·분위기만 맞추고, 얼굴형·이목구비·피부톤·
  헤어스타일·헤어 컬러·의상(종류·색·디자인)·액세서리는 확실히 다르게. 의상에 브랜드 로고 없음.
  그림체가 애니메이션이면 그 그림체의 캐릭터로 묘사. 레퍼런스에 사람이 전혀 없으면 빈 문자열.
- concept_note (한국어, 3~5줄): "레퍼런스에서 가져온 것: …" / "새로 만든 것: …" 형식으로 사용자에게 보여 줄 요약.
- scenes: 새 대사 장면마다
  - prompt (영어): 이 장면 이미지 한 장. 새 대사의 내용을 보여 주는 장면을 설계한다. 같은 위치 레퍼런스 컷의
    '역할'(후킹·문제 제기·시연·증거·CTA)을 살리고, 구도·앵글·동작은 맨 위 [장면 구성] 지시만큼 레퍼런스 컷을 따른다.
    첫 장면은 레퍼런스의 후킹 방식을 살려 시선을 끄는 장면으로. 모든 장면이 같은 style_guide·world·character를 따른다.
    인물이 나오면 character를 같은 말로 묘사하고, 제품이 나오면 손 대비 실제 크기와 자연스러운 합성을 묘사한다.
    글자·자막·로고 텍스트는 넣지 않는다.
  - motion (영어 짧은 구): 이미지→영상 카메라 움직임과 피사체 동작 (예: "slow push-in, she lifts the pouch toward camera").
  - has_person: 인물이 나오는지.
- product_scale (영어): 제품 사진 중 손에 들고 찍은 사진으로 판단한 실제 크기.
  예: "The sachet pouch is about 9 cm square — slightly smaller than an adult palm."
- product_images: 첨부된 제품 사진마다 번호(n, 1부터)와 역할(role).
  in_hand = 사람 손에 들고 있어 실제 크기를 알 수 있는 사진, packaging = 패키지 정면·누끼, other = 그 밖의 연출.

[제품 합성]
- 제품의 외형(모양·색·라벨)은 제품 사진을 따르되, 그림체가 애니메이션·일러스트면 그 그림체로 자연스럽게 녹여 그린다.
- 장면과 같은 조명 방향·색온도·노출, 자연스러운 그림자와 접촉 그림자, 포장재 질감, 손가락이 제품을 실제로 잡는 모습,
  같은 원근·심도를 묘사해 붙여 넣은 티가 나지 않게 한다."""


REVISE_SYSTEM = """당신은 숏폼 광고 이미지·영상 프롬프트를 고치는 아트 디렉터입니다.
현재 장면 프롬프트(영어)와 사용자의 수정 지시(한국어)를 받습니다.
수정 지시를 정확하고 구체적으로 반영한 새 프롬프트를 영어로 쓰세요.
- 지시하지 않은 부분(그림체·인물·세계관·제품 묘사·크기·합성 지시)은 그대로 유지합니다.
- 지시가 모호하면 장면의 대사와 목적에 맞게 가장 자연스러운 쪽으로 구체화합니다.
- 글자·자막·로고 텍스트는 넣지 않습니다.
- change_summary: 무엇을 바꿨는지 한국어 한 줄."""


@dataclass
class Briefs:
    scenes: dict[str, dict]  # {scene_id: {"prompt", "motion", "has_person"}}
    character: str = ""
    product_scale: str = ""
    product_roles: dict[str, str] = field(default_factory=dict)  # {제품 폴더 기준 경로: 역할}
    style_guide: str = ""
    world: str = ""
    concept_note: str = ""


def _schema() -> dict:
    scene = strict_object({"scene_id": {"type": "string"}, "prompt": {"type": "string"}, "motion": {"type": "string"},
                           "has_person": {"type": "boolean"}})
    image = strict_object({"n": {"type": "integer"}, "role": {"type": "string", "enum": [ROLE_HAND, ROLE_PACKAGING, ROLE_OTHER]}})
    return strict_object({
        "style_guide": {"type": "string"},
        "world": {"type": "string"},
        "character": {"type": "string"},
        "concept_note": {"type": "string"},
        "product_scale": {"type": "string"},
        "product_images": {"type": "array", "items": image},
        "scenes": {"type": "array", "items": scene},
    })


def product_image_entries(project_id: str) -> list[tuple[str, Path]]:
    """[(제품 폴더 기준 경로, 실제 경로)] — 연출컷 다음 누끼컷 순서."""
    product = store.get_product(project_id)
    pdir = store.product_dir(project_id)
    return [(img.path, pdir / img.path) for img in product.images.styled + product.images.cutout if (pdir / img.path).exists()]


def product_images(project_id: str) -> list[Path]:
    return [p for _, p in product_image_entries(project_id)]


def reference_for(project_id: str, ref_index: int | None) -> dict | None:
    analysis = store.get_scene_analysis(project_id)
    if not analysis or ref_index is None:
        return None
    return next((s for s in analysis["scenes"] if s["index"] == ref_index), None)


def style_frames(project_id: str, avoid_index: int | None, limit: int = 2) -> list[Path]:
    """그림체 참고용 레퍼런스 프레임. 기준 장면과 대응하는 구간은 피하고 영상 전체에서 고르게 고른다
    (한 장면을 통째로 베끼지 않도록 '그림체 견본'으로만 쓴다)."""
    analysis = store.get_scene_analysis(project_id)
    if not analysis:
        return []
    scenes = [s for s in analysis["scenes"] if s.get("frames") and s["index"] != avoid_index] or \
             [s for s in analysis["scenes"] if s.get("frames")]
    if not scenes:
        return []
    picks = [scenes[round(i * (len(scenes) - 1) / max(1, limit - 1))] for i in range(min(limit, len(scenes)))]
    out: list[Path] = []
    for s in picks:
        p = store.project_dir(project_id) / s["frames"][len(s["frames"]) // 2]
        if p.exists() and p not in out:
            out.append(p)
    return out


def _overall_text(project_id: str) -> str:
    analysis = store.get_analysis(project_id)
    if not analysis:
        return "-"
    o = analysis.overall
    structure = " → ".join(f"{p.role}({p.start:.0f}–{p.end:.0f}초: {p.summary})" for p in o.structure) or "-"
    return (
        f"컨셉: {o.concept or '-'}\n"
        f"비주얼 스타일(그림체·촬영·색감·편집): {o.visual_style or '-'}\n"
        f"화자 페르소나: {o.persona.age} {o.persona.gender} · {o.persona.character} · 신뢰 요소: {o.persona.credibility}\n"
        f"말투: {o.tone.speech_level} · {o.tone.pace} · {o.tone.description}\n"
        f"전개 구성: {structure}"
    )


FOLLOW_RULES = {
    "low": "레퍼런스 장면의 역할과 샷 크기 정도만 참고하고, 구도·동작은 새로 설계한다.",
    "medium": ("[장면 구성 — 레퍼런스 컷 따라가기: 보통]\n"
               "각 장면은 같은 위치 레퍼런스 장면의 샷 크기, 카메라 앵글·높이·거리, 화면 속 피사체 위치·비중, 인물의 동작·제스처,"
               " 제품 노출 방식을 따른다. 배경·소품·인물 외모·의상·색감은 world·character·style_guide로 새로 그린다."),
    "high": ("[장면 구성 — 레퍼런스 컷 따라가기: 강하게]\n"
             "각 장면은 같은 위치 레퍼런스 장면의 샷 크기, 카메라 앵글·높이·거리, 피사체 위치·비중, 동작·제스처, 제품 노출 방식에 더해"
             " 배경의 종류와 배치(예: 욕실 거울 앞, 책상 위, 침대 위)까지 비슷하게 맞춘다. 단 인물의 얼굴·헤어·의상, 소품의 디자인,"
             " 색감·그림체는 레퍼런스를 복사하지 않고 character·style_guide로 새로 그린다. world는 이 장소들을 아우르는 설정으로 쓴다."),
}


def build_briefs(project_id: str) -> Briefs:
    """Claude 미연결 시 레퍼런스 장면 요약을 그대로 쓴다 (임시)."""
    script = store.get_script(project_id)
    entries = product_image_entries(project_id)

    if not claude_client.is_configured():
        out = {}
        for s in script.scenes:
            ref = reference_for(project_id, s.ref_segment)
            out[s.id] = {"prompt": ref["scene"] if ref else "", "motion": "slow zoom-in", "has_person": True}
        roles = {rel: ROLE_PACKAGING if rel.startswith("cutout/") else ROLE_OTHER for rel, _ in entries}
        return Briefs(scenes=out, product_roles=roles)

    product = store.get_product(project_id)
    follow = store.get_production(project_id).visual.ref_follow or "medium"
    lines = [
        FOLLOW_RULES.get(follow, FOLLOW_RULES["medium"]),
        "",
        f"화면 비율: {script.meta.aspect_ratio}",
        "[레퍼런스 영상 전체 분석 — 빌려 올 특징]",
        _overall_text(project_id),
        "",
        f"자사 제품: {product.name} — {product.usp}",
        f"제품 특징: {' / '.join(product.features) or '-'}",
        f"추가 정보(크기 등): {product.extra or '-'}",
        "",
        "[새 영상 장면 — 장면마다 prompt를 설계. '레퍼런스 컷'은 같은 위치 레퍼런스 장면의 구성 정보]",
    ]
    for s in script.scenes:
        ref = reference_for(project_id, s.ref_segment)
        d = (ref or {}).get("detail") or {}
        ref_hint = [f"역할 {s.role or '-'}", f"샷 {ref.get('shot_type', '-') if ref else '-'}"]
        if follow in ("medium", "high") and ref:
            ref_hint += [f"구도·앵글: {d.get('composition') or '-'}", f"동작·제스처: {d.get('action') or '-'}",
                         f"제품 노출: {d.get('product') or '-'}"]
        if follow == "high" and ref:
            ref_hint.append(f"배경 종류·배치: {d.get('background') or '-'}")
        lines.append(
            f"[scene_id={s.id}] {s.start:.1f}–{s.end:.1f}초\n"
            f"  레퍼런스 컷: {' / '.join(ref_hint)}\n"
            f"  새 대사: {' / '.join(split_sentences(s.dialogue)) or '(없음)'}"
        )
    content: list[dict] = [{"type": "text", "text": "\n".join(lines)}]
    frames = style_frames(project_id, None, limit=3)
    if frames:
        content.append({"type": "text", "text": "[레퍼런스 영상 프레임 — 그림체·색감·조명 분위기만 읽을 것. 인물·배경·구도는 쓰지 말 것]"})
        content += [claude_client.image_block(p) for p in frames]
    if entries:
        content.append({"type": "text", "text": f"[자사 제품 사진 {len(entries)}장 — 아래 순서대로 1번부터]"})
        for n, (rel, path) in enumerate(entries, 1):
            kind = "누끼컷" if rel.startswith("cutout/") else "연출컷"
            content.append({"type": "text", "text": f"{n}번 ({kind})"})
            content.append(claude_client.image_block(path))
    result = claude_client.json_call(BRIEF_SYSTEM, [{"role": "user", "content": content}], _schema())

    roles = {}
    for item in result.get("product_images", []):
        if 1 <= item["n"] <= len(entries):
            roles[entries[item["n"] - 1][0]] = item["role"]
    return Briefs(
        scenes={r["scene_id"]: {"prompt": r["prompt"], "motion": r["motion"], "has_person": r["has_person"]} for r in result.get("scenes", [])},
        character=result.get("character", "").strip(),
        product_scale=result.get("product_scale", "").strip(),
        product_roles=roles,
        style_guide=result.get("style_guide", "").strip(),
        world=result.get("world", "").strip(),
        concept_note=result.get("concept_note", "").strip(),
    )


def _revise(kind: str, current: str, instruction: str, dialogue: str) -> tuple[str, str]:
    """(새 프롬프트, 바꾼 내용 요약). Claude가 없으면 지시를 덧붙인다."""
    if not claude_client.is_configured():
        return f"{current}\n\nRevision requested by the user (Korean): {instruction}", instruction
    schema = strict_object({"prompt": {"type": "string"}, "change_summary": {"type": "string"}})
    text = (f"[{kind}]\n장면 대사: {dialogue or '(없음)'}\n\n현재 프롬프트:\n{current or '(없음)'}\n\n"
            f"사용자 수정 지시:\n{instruction}")
    res = claude_client.json_call(REVISE_SYSTEM, [{"role": "user", "content": text}], schema)
    return res.get("prompt", "").strip() or current, res.get("change_summary", "").strip()


def revise_image_prompt(current: str, instruction: str, dialogue: str) -> str:
    return _revise("이미지 프롬프트 — 한 장의 정지 이미지", current, instruction, dialogue)[0]


def revise_video_prompt(current: str, instruction: str, dialogue: str) -> str:
    return _revise("영상 프롬프트 — 이미지→영상 변환 시 카메라 움직임과 피사체 동작 (짧고 구체적으로)", current, instruction, dialogue)[0]
