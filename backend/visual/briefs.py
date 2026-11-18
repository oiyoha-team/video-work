"""장면별 이미지 브리프(프롬프트·카메라 움직임)를 영상 제작 단계에서 만든다.

입력: 레퍼런스 장면 분석(scene_analysis/scenes.json) + 자사 대사(script.json) + 제품 정보·이미지.

- 레퍼런스에서는 구도·카메라·동작·배경 구성·조명·색감만 가져온다. 인물은 그대로 쓰지 않고
  성별·연령대·체형·분위기만 맞춘 '새 인물'(character)을 정해 모든 장면에 같은 사람으로 쓴다.
- 제품 이미지는 장면에 배정하지 않고 참고 자료로 넘긴다. 손에 든 사진으로 실제 크기(product_scale)를 읽고,
  사진마다 역할(손에 든 크기 비교 / 패키지 / 연출)을 표시해 이미지 생성 때 역할에 맞게 쓴다.
"""
from dataclasses import dataclass, field
from pathlib import Path

from llm import claude_client
from llm.claude_client import strict_object
from planning import store
from planning.labels import detail_text
from planning.text import split_sentences
from schemas import SceneDetail

# 제품 사진 역할
ROLE_HAND = "in_hand"  # 실제 손에 들고 찍은 사진 → 실제 크기 기준
ROLE_PACKAGING = "packaging"  # 패키지 정면·누끼 → 외형 기준
ROLE_OTHER = "other"

BRIEF_SYSTEM = """당신은 숏폼 광고의 장면 이미지를 설계하는 아트 디렉터입니다.
레퍼런스 영상의 장면 분석과, 자사 제품으로 바꾼 새 대사, 자사 제품 정보·사진을 받습니다.
장면마다 이미지 생성 AI에 넣을 영어 프롬프트와 이미지→영상 변환 시 카메라 움직임을 만드세요.

[레퍼런스에서 가져오는 것]
- 구도, 카메라 앵글·거리, 인물의 자세·동작·제스처, 배경의 구성(공간 종류·배치), 조명 방향, 색감, 스마트폰 UGC 화질.
- 새 대사 내용과 어긋나는 부분만 바꾼다. 영상 전체 비주얼 스타일을 모든 장면에 일관되게 적용한다.

[인물: 레퍼런스 인물을 그대로 쓰면 안 된다]
- 레퍼런스 인물과 성별·연령대·체형·전체 분위기만 비슷한 '새 인물'을 설정해 character에 영어로 자세히 쓴다.
  얼굴형, 이목구비(눈·코·입·눈썹), 피부톤, 헤어스타일·헤어 컬러, 의상(종류·색·디자인), 액세서리를
  레퍼런스와 확실히 다르게 정한다. 의상에는 어떤 브랜드 로고도 넣지 않는다.
- 인물이 나오는 모든 장면의 prompt에 이 새 인물을 같은 말로 묘사해 같은 사람으로 보이게 한다.
  레퍼런스 인물의 외모·옷(예: 레퍼런스의 검은 티셔츠, 투블럭 머리)을 prompt에 쓰지 않는다.
- 인물이 없는 장면(제품만, 음식만 등)은 has_person=false.
- 레퍼런스에 인물이 전혀 없으면 character는 빈 문자열.

[제품: 크기와 합성]
- 제품 사진 중 사람 손에 들고 찍은 사진으로 실제 크기를 판단해 product_scale에 영어로 쓴다.
  예: "The sachet pouch is about 9 cm square — slightly smaller than an adult palm; each tablet is about 1.5 cm long."
- product_images: 첨부된 제품 사진마다 번호(n, 1부터)와 역할(role)을 정한다.
  in_hand = 사람 손에 들고 있어 실제 크기를 알 수 있는 사진, packaging = 패키지 정면·누끼, other = 그 밖의 연출.
- 레퍼런스에 다른 제품이 보이면 자사 제품으로 바꾼다. 외형(모양·색·라벨)은 제품 사진을 따른다.
- 제품이 나오는 장면의 prompt에는 손 대비 실제 크기를 명시하고, 합성처럼 보이지 않게
  장면과 같은 조명 방향·색온도·노출, 자연스러운 그림자와 접촉 그림자, 포장재의 실제 질감(무광/유광 반사, 살짝 구겨짐),
  손가락이 제품 가장자리를 실제로 잡고 가리는 모습, 장면과 같은 원근·심도를 묘사한다.

[형식]
- prompt: 영어. 피사체·행동·배경·구도·카메라 앵글·조명·색감·화면 비율을 구체적으로. 글자·자막·로고 텍스트는 넣지 않는다.
- motion: 영어 짧은 구 (예: "slow zoom-in", "handheld pan left", "static")."""


@dataclass
class Briefs:
    scenes: dict[str, dict]  # {scene_id: {"prompt", "motion", "has_person"}}
    character: str = ""
    product_scale: str = ""
    product_roles: dict[str, str] = field(default_factory=dict)  # {제품 폴더 기준 경로: 역할}


def _schema() -> dict:
    scene = strict_object({"scene_id": {"type": "string"}, "prompt": {"type": "string"}, "motion": {"type": "string"},
                           "has_person": {"type": "boolean"}})
    image = strict_object({"n": {"type": "integer"}, "role": {"type": "string", "enum": [ROLE_HAND, ROLE_PACKAGING, ROLE_OTHER]}})
    return strict_object({
        "character": {"type": "string"},
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


def build_briefs(project_id: str) -> Briefs:
    """Claude 미연결 시 레퍼런스 장면 요약을 그대로 쓴다."""
    script = store.get_script(project_id)
    analysis = store.get_scene_analysis(project_id) or {"scenes": [], "visual_style": ""}
    entries = product_image_entries(project_id)

    if not claude_client.is_configured():
        out = {}
        for s in script.scenes:
            ref = reference_for(project_id, s.ref_segment)
            out[s.id] = {"prompt": ref["scene"] if ref else "", "motion": "slow zoom-in", "has_person": True}
        roles = {rel: ROLE_PACKAGING if rel.startswith("cutout/") else ROLE_OTHER for rel, _ in entries}
        return Briefs(scenes=out, product_roles=roles)

    product = store.get_product(project_id)
    lines = [
        f"화면 비율: {script.meta.aspect_ratio}",
        f"영상 전체 비주얼 스타일: {analysis.get('visual_style') or '-'}",
        f"자사 제품: {product.name} — {product.usp}",
        f"제품 특징: {' / '.join(product.features) or '-'}",
        f"추가 정보(크기 등): {product.extra or '-'}",
        "",
    ]
    for s in script.scenes:
        ref = reference_for(project_id, s.ref_segment)
        detail = detail_text(SceneDetail.model_validate(ref["detail"]), "    ") if ref else ""
        lines.append(
            f"[scene_id={s.id}] {s.start:.1f}–{s.end:.1f}초\n"
            f"  레퍼런스 장면: {ref['scene'] if ref else '-'} (샷: {ref.get('shot_type', '-') if ref else '-'})\n{detail}\n"
            f"  새 대사: {' / '.join(split_sentences(s.dialogue)) or '(없음)'}"
        )
    content: list[dict] = [{"type": "text", "text": "\n".join(lines)}]
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
    )
