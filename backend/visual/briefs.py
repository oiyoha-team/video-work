"""장면별 이미지 브리프(프롬프트·카메라 움직임)를 영상 제작 단계에서 만든다.

입력: 레퍼런스 장면 분석(scene_analysis/scenes.json) + 자사 대사(script.json) + 제품 정보·이미지.
제품 이미지(연출컷·누끼컷)는 장면에 배정하지 않고, 제품 외형을 정확히 그리기 위한 참고 자료로 모두 넘긴다.
"""
from pathlib import Path

from llm import claude_client
from llm.claude_client import strict_object
from planning import store
from planning.labels import detail_text
from planning.text import split_sentences
from schemas import SceneDetail

BRIEF_SYSTEM = """당신은 숏폼 광고의 장면 이미지를 설계하는 아트 디렉터입니다.
레퍼런스 영상의 장면 분석과, 자사 제품으로 바꾼 새 대사를 받습니다.
장면마다 이미지 생성 AI에 넣을 영어 프롬프트와 이미지→영상 변환 시 카메라 움직임을 만드세요.

규칙:
- 각 장면은 같은 index의 레퍼런스 장면(구도·카메라 앵글·인물·배경·조명·색감)을 최대한 비슷하게 재현한다.
  새 대사 내용과 어긋나는 부분만 바꾼다.
- 레퍼런스에 다른 제품이 보이면 자사 제품으로 바꾼다. 자사 제품의 외형(용기 모양·색·라벨)은 첨부된 제품 이미지를 따른다.
- 영상 전체 비주얼 스타일을 모든 장면에 일관되게 적용한다.
- prompt: 영어. 피사체·행동·배경·구도·카메라 앵글·조명·색감·화면 비율을 구체적으로. 글자·자막·로고 텍스트는 넣지 않는다.
- motion: 영어 짧은 구 (예: "slow zoom-in", "handheld pan left", "static")."""


def _schema() -> dict:
    item = strict_object({"scene_id": {"type": "string"}, "prompt": {"type": "string"}, "motion": {"type": "string"}})
    return strict_object({"scenes": {"type": "array", "items": item}})


def product_images(project_id: str) -> list[Path]:
    product = store.get_product(project_id)
    pdir = store.product_dir(project_id)
    return [pdir / img.path for img in product.images.styled + product.images.cutout if (pdir / img.path).exists()]


def reference_for(project_id: str, ref_index: int | None) -> dict | None:
    analysis = store.get_scene_analysis(project_id)
    if not analysis or ref_index is None:
        return None
    return next((s for s in analysis["scenes"] if s["index"] == ref_index), None)


def build_briefs(project_id: str) -> dict[str, dict]:
    """{scene_id: {"prompt", "motion"}}. Claude 미연결 시 레퍼런스 장면 요약을 그대로 쓴다."""
    script = store.get_script(project_id)
    analysis = store.get_scene_analysis(project_id) or {"scenes": [], "visual_style": ""}

    if not claude_client.is_configured():
        out = {}
        for s in script.scenes:
            ref = reference_for(project_id, s.ref_segment)
            out[s.id] = {"prompt": ref["scene"] if ref else "", "motion": "slow zoom-in"}
        return out

    product = store.get_product(project_id)
    lines = [
        f"화면 비율: {script.meta.aspect_ratio}",
        f"영상 전체 비주얼 스타일: {analysis.get('visual_style') or '-'}",
        f"자사 제품: {product.name} — {product.usp}",
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
    images = product_images(project_id)
    if images:
        content.append({"type": "text", "text": "[자사 제품 이미지 — 외형 참고용]"})
        content += [claude_client.image_block(p) for p in images]
    result = claude_client.json_call(BRIEF_SYSTEM, [{"role": "user", "content": content}], _schema())
    return {r["scene_id"]: {"prompt": r["prompt"], "motion": r["motion"]} for r in result.get("scenes", [])}
