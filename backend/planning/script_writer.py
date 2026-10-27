"""Step 3: 레퍼런스 구조 + 자사 제품 정보 → 새 대사 스크립트(script.json).

장면은 Step 1에서 확정된 구간과 1:1로 대응하고 (2초 리듬 유지),
대사는 문장 단위로 레퍼런스 문장과 1:1 치환한다 (한 줄 = 한 문장 = TTS 파일 하나).
기획 단계에서는 대사만 다룬다. 화면(이미지)은 영상 제작 단계에서 장면 분석을 바탕으로 만든다.
"""
import json
import traceback

from llm import claude_client
from llm.claude_client import strict_object
from schemas import JobState, Product, ReferenceAnalysis, Scene, Script, ScriptMeta, Voice

from . import store
from .labels import fmt_time
from .text import split_sentences, to_lines

SYLLABLES_PER_SEC = 5  # 빠른 광고 내레이션 기준 대략적인 한국어 발화 속도

WRITER_SYSTEM = """당신은 한국 퍼포먼스 광고(숏폼) 전문 카피라이터입니다.
레퍼런스 영상의 구간별 구성·말투·페르소나를 그대로 살리면서, 내용만 자사 제품으로 바꾼 새 대사 스크립트를 씁니다.

반드시 지킬 것:
1. 구간 수와 순서를 그대로 유지한다. 레퍼런스 구간 하나당 장면 하나 (ref_index로 대응).
2. 각 구간의 역할(훅/문제제기/해결책 등)과 리듬을 유지한다. 장면 요약은 대사 흐름을 이해하는 참고용이다.
3. 레퍼런스의 말투(존댓말/반말, 어미, 말버릇)와 화자 페르소나를 그대로 따른다.
4. 대사는 문장 단위로 쓴다. lines 배열의 원소 하나 = 한 문장 = 나중에 음성 파일 하나.
   - 레퍼런스 구간의 문장 (1), (2)… 를 같은 개수·같은 순서로 1:1 치환한다 (문장을 합치거나 나누지 않는다).
   - 각 문장은 마침표(.)·물음표(?)·느낌표(!) 중 하나로 끝낸다.
   - 레퍼런스 문장과 비슷한 길이로, 구간 길이 안에 말할 수 있게 쓴다 (구간 길이(초) × 약 5음절).
   - 레퍼런스 구간에 대사가 없으면 lines는 빈 배열.
5. 제품의 USP와 특징을 자연스럽게 녹인다. 제공되지 않은 효능·수치·사실은 지어내지 않는다.
   - '사회적·수치적 근거 및 권위'의 수치·성분명·비교 표현은 주어진 그대로만 쓴다 (바꾸거나 부풀리지 않는다).
   - 제품을 부를 때는 제품명 또는 '제품 지칭 키워드' 중 레퍼런스 말투에 어울리는 것을 쓴다.
6. 들어가면 안 되는 표현은 절대 쓰지 않는다. 의약품 오인, 과장(100%, 완치, 최고 등) 표현을 피한다.
7. voice는 TTS 설정용 짧은 값으로 쓴다: persona는 한 줄(예: "20대 후반 여성, 친근한 실사용자"),
   speech_level은 "존댓말"/"반말"/"혼용" 중 하나, pace는 "빠름"/"보통"/"느림" 중 하나, emotion은 2~4단어."""


def _numbered(dialogue: str) -> str:
    sentences = split_sentences(dialogue)
    return "".join(f"\n    ({n}) {s}" for n, s in enumerate(sentences, 1)) if sentences else " (없음)"


def _context_text(analysis: ReferenceAnalysis, product: Product) -> str:
    o = analysis.overall
    lines = [
        "## 레퍼런스 전체 분석",
        f"- 말투: {o.tone.speech_level} / {o.tone.pace} / {o.tone.description}",
        f"- 말버릇: {', '.join(o.tone.habits) or '-'}",
        f"- 컨셉: {o.concept}",
        f"- 페르소나: {o.persona.age} {o.persona.gender}, {o.persona.character} (신뢰 근거: {o.persona.credibility})",
        "",
        "## 레퍼런스 구간",
    ]
    for s in analysis.segments:
        dur = s.end - s.start
        lines.append(
            f"[ref_index={s.index}] {fmt_time(s.start)}–{fmt_time(s.end)} ({dur:.1f}초, 권장 대사 ≤{int(dur * SYLLABLES_PER_SEC)}음절) "
            f"역할={s.role or '-'}\n  장면 요약: {s.scene or '-'}\n"
            f"  대사 ({len(split_sentences(s.dialogue))}문장):{_numbered(s.dialogue)}"
        )
    lines += [
        "",
        "## 자사 제품",
        f"- 제품명: {product.name}",
        f"- 제품 USP: {product.usp or '-'}",
        "- 제품 특징:\n" + "\n".join(f"  - {f}" for f in product.features),
        f"- 사회적·수치적 근거 및 권위: {product.evidence or '-'}",
        f"- 제품 지칭 키워드: {', '.join(product.keywords) or '-'}",
        f"- 들어가면 안 되는 표현: {', '.join(product.forbidden_phrases) or '없음'}",
        f"- 기타 메모: {product.extra or '-'}",
    ]
    return "\n".join(lines)


def _scene_schema() -> dict:
    return strict_object({
        "ref_index": {"type": "integer"},
        "lines": {"type": "array", "items": {"type": "string"}},
    })


def _join_lines(raw: dict) -> str:
    return "\n".join(to_lines(line) for line in raw.get("lines", []) if line.strip())


def _base_meta(project_id: str, analysis: ReferenceAnalysis, product: Product, title: str) -> ScriptMeta:
    project = store.get_project(project_id)
    return ScriptMeta(
        title=title or f"{product.name} 퍼포먼스 영상",
        product_name=product.name,
        product_library_id=product.library_id,
        reference=analysis.source.file,
        total_duration_sec=analysis.source.duration_sec,
        aspect_ratio=project.aspect_ratio or analysis.source.detected_aspect_ratio,
    )


def _scenes(analysis: ReferenceAnalysis, dialogue_for) -> list[Scene]:
    return [
        Scene(id=f"s{i + 1:02d}", start=seg.start, end=seg.end, role=seg.role, dialogue=dialogue_for(seg), ref_segment=seg.index)
        for i, seg in enumerate(analysis.segments)
    ]


def _mock_script(project_id: str, analysis: ReferenceAnalysis, product: Product) -> Script:
    """Claude 미연결 시: 레퍼런스 대사를 그대로 복사해 UI 흐름을 테스트할 수 있게 한다."""
    o = analysis.overall
    return Script(
        mock=True,
        meta=_base_meta(project_id, analysis, product, ""),
        voice=Voice(persona=f"{o.persona.age} {o.persona.gender} {o.persona.character}".strip(), speech_level=o.tone.speech_level, pace=o.tone.pace),
        scenes=_scenes(analysis, lambda seg: seg.dialogue),
    )


def generate_script(project_id: str) -> Script:
    analysis = store.get_analysis(project_id)
    product = store.get_product(project_id)
    if analysis is None:
        raise ValueError("레퍼런스 분석이 없습니다.")
    if not claude_client.is_configured():
        return _mock_script(project_id, analysis, product)

    schema = strict_object({
        "title": {"type": "string"},
        "voice": strict_object({
            "persona": {"type": "string"},
            "speech_level": {"type": "string"},
            "pace": {"type": "string"},
            "emotion": {"type": "string"},
        }),
        "scenes": {"type": "array", "items": _scene_schema()},
    })
    prompt = _context_text(analysis, product) + f"\n\n총 {len(analysis.segments)}개 구간 모두에 대해 대사를 작성하세요."
    result = claude_client.json_call(WRITER_SYSTEM, [{"role": "user", "content": prompt}], schema, effort="high")

    by_ref = {r["ref_index"]: r for r in result.get("scenes", [])}
    return Script(
        meta=_base_meta(project_id, analysis, product, result.get("title", "")),
        voice=Voice.model_validate(result.get("voice", {})),
        scenes=_scenes(analysis, lambda seg: _join_lines(by_ref.get(seg.index, {}))),
    )


def regenerate_scene(project_id: str, scene_id: str, instruction: str = "") -> Script:
    claude_client._get_client()  # 미연결이면 여기서 ClaudeNotConfigured
    analysis = store.get_analysis(project_id)
    product = store.get_product(project_id)
    script = store.get_script(project_id)
    if analysis is None or script is None:
        raise ValueError("스크립트가 없습니다.")
    scene = next((s for s in script.scenes if s.id == scene_id), None)
    if scene is None:
        raise ValueError(f"장면 {scene_id}를 찾을 수 없습니다.")

    current = "\n".join(f"{s.id}: {' / '.join(split_sentences(s.dialogue)) or '-'}" for s in script.scenes)
    prompt = (
        _context_text(analysis, product)
        + f"\n\n## 현재 대사 스크립트\n{current}"
        + f"\n\n장면 {scene_id} (ref_index={scene.ref_segment}) 하나만 새로 작성하세요. 앞뒤 장면과 자연스럽게 이어져야 합니다."
        + (f"\n추가 요청: {instruction}" if instruction else "")
    )
    raw = claude_client.json_call(WRITER_SYSTEM, [{"role": "user", "content": prompt}], _scene_schema())
    scene.dialogue = _join_lines(raw)
    return script


def run_generate(project_id: str) -> None:
    """백그라운드 실행. 진행 상황은 project.json의 script_job에 기록."""
    try:
        store.update_project(project_id, script_job=JobState(status="running", progress=0.1, message="스크립트 작성 중"))
        script = generate_script(project_id)
        store.save_script(project_id, script)
        store.save_chat(project_id, [])
        store.update_project(project_id, script_job=JobState(status="done", progress=1, message="작성 완료"))

        import gates  # 순환 import 방지
        hook = next((split_sentences(s.dialogue)[0] for s in script.scenes if s.dialogue.strip()), "")
        gates.open_gate(project_id, "script", f"「{script.meta.title}」 · 장면 {len(script.scenes)}개\n훅: 「{hook}」")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        store.update_project(project_id, script_job=JobState(status="error", message=str(e) or e.__class__.__name__))


# ── 내보내기 ─────────────────────────────────────────────

def to_text(script: Script) -> str:
    """최종 기획안 텍스트: 대사 스크립트만 (한 줄 = 한 문장)."""
    lines = [sentence for s in script.scenes for sentence in split_sentences(s.dialogue)]
    return "\n".join(lines) + "\n" if lines else ""


def script_json_for_prompt(script: Script) -> str:
    return json.dumps([{"scene_id": s.id, "dialogue": s.dialogue} for s in script.scenes], ensure_ascii=False)
