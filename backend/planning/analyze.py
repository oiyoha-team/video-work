"""Step 1: 레퍼런스 영상 분석 파이프라인.

프레임/오디오 추출 → STT → 1초 구간 배정 → 동일 대사 병합 → 화면 전환 감지로 구간 안의 컷 나누기
→ Claude Vision 구간·컷 분석 → 전체 톤/컨셉/페르소나 분석
"""
import traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from errors import explain
from llm import claude_client
from llm.claude_client import strict_object
from schemas import JobState, Overall, RefCut, ReferenceAnalysis, SceneDetail, Segment, SourceInfo

from . import store, transcribe, video_ingest
from .labels import ROLES, SCENE_DETAIL, SHOT_TYPES, detail_text, fmt_time

VISION_BATCH = 6  # 한 번에 분석할 구간 수 (구간마다 컷 프레임이 여러 장)
MAX_CUT_FRAMES = 8  # 구간 하나에서 Claude에게 보여 줄 컷 프레임 최대 수
VISION_PARALLEL = 3

MOCK_NOTE = "(Claude 미연결 — 직접 입력하거나 API 키 연결 후 재분석)"


def _set_job(project_id: str, status: str, progress: float, message: str) -> None:
    store.update_project(project_id, analysis_job=JobState(status=status, progress=progress, message=message))


def merge_identical_dialogue(segments: list[Segment], keys: list[list[int]],
                             cut_times: list[float] | None = None) -> tuple[list[Segment], list[list[int]]]:
    """1초 구간을 장면으로 묶는다. 다음 경우에만 앞 구간에 합친다.

    1. 대사(문장 목록)가 앞 구간과 '완전히 동일' (한 문장이 여러 초에 걸침)
    2. 새 대사가 없고, 경계에서 화면도 바뀌지 않음 (같은 장면이 이어짐 → 같은 이미지를 중복으로 만들지 않게)
    문장이 하나라도 다르거나, 대사 없는 구간이라도 화면이 바뀌면 새 장면이다.
    cut_times가 없으면(예전 방식) 2번 규칙은 쓰지 않는다.
    """
    merged: list[Segment] = []
    merged_keys: list[list[int]] = []
    for seg, key in zip(segments, keys):
        same_dialogue = bool(key) and key == (merged_keys[-1] if merged else None)
        same_shot_silent = (cut_times is not None and merged and not key
                            and not video_ingest.has_cut_at(seg.start, cut_times))
        if merged and (same_dialogue or same_shot_silent):
            prev = merged[-1]
            prev.end = seg.end
            prev.frames.extend(seg.frames)
            prev.merged_from.append(seg.index)
            continue
        seg.merged_from = [seg.index]
        merged.append(seg)
        merged_keys.append(list(key))
    for i, seg in enumerate(merged):
        seg.index = i
    return merged, merged_keys


def merge_silent_same_shot(segments: list[Segment], cut_times: list[float]) -> list[Segment]:
    """문장을 한 구간에만 남긴 뒤 대사가 비게 된 구간도, 경계에서 화면이 그대로면 앞 장면에 합친다."""
    out: list[Segment] = []
    for seg in segments:
        if out and not seg.dialogue.strip() and not video_ingest.has_cut_at(seg.start, cut_times):
            prev = out[-1]
            prev.end = seg.end
            prev.frames.extend(seg.frames)
            prev.merged_from.extend(seg.merged_from)
            continue
        out.append(seg)
    for i, seg in enumerate(out):
        seg.index = i
    return out


# ── Claude 호출 ─────────────────────────────────────────────

VISION_SYSTEM = """당신은 한국 퍼포먼스 광고(숏폼) 영상 분석 전문가입니다.
레퍼런스 영상을 1초 단위로 나눈 뒤 같은 대사끼리 묶은 구간과, 구간 안의 컷(화면 전환 기준)별 프레임,
음성 인식(STT)으로 얻은 구간별 대사를 받습니다.
각 구간을 정확히 분석해 JSON으로 반환하세요.
이 분석은 나중에 AI 이미지 생성으로 '레퍼런스와 비슷한 장면'을 다시 만드는 기준이 됩니다.
프레임만 보고도 같은 장면을 그릴 수 있을 만큼 구체적으로, 보이는 사실만 쓰세요 (추측은 '~로 보임').

규칙:
- scene: 장면 요약. 한국어 1~2문장.
- detail: 장면 상세 (모두 한국어, 해당 없으면 빈 문자열)
  - subject: 피사체·인물 — 나이대, 성별, 외모, 헤어, 메이크업, 의상과 색
  - action: 행동·표정·제스처·시선 (카메라를 보는지 등)
  - background: 장소, 배경, 소품, 공간 분위기
  - composition: 샷 크기, 카메라 앵글(정면/하이/로우/탑뷰), 셀카·거치 여부, 피사체 위치와 화면 비중, 화면 분할
  - lighting: 조명 방향·세기, 색감, 톤(따뜻함/차가움, 채도), 필터 느낌
  - product: 제품 노출 방식 (손에 듦, 바르는 장면, 클로즈업, 패키지 정면, 미노출 등)
- dialogue: STT 대사를 기본으로 사용. 화면에 같은 문장이 보이면 그것과 비교해 명백한 오인식(맞춤법·고유명사)만 고친다.
  STT 대사는 한 줄에 한 문장이다. 줄 수와 순서를 그대로 유지하고(줄바꿈 \\n), 각 문장은 . ? ! 로 끝낸다.
  절대 문장을 요약·합치기·나누기·다른 구간으로 옮기지 말 것. STT 대사가 비어 있으면 빈 문자열.
- cuts: 구간 안의 컷마다 (n = 주어진 컷 번호 그대로) description을 쓴다. 한국어 2~3문장으로
  샷 크기, 카메라 앵글·거리, 피사체와 화면 속 위치·비중, 인물의 동작·제스처·시선, 배경 종류와 배치, 제품 노출 방식을
  그 컷 프레임에 보이는 그대로 구체적으로. 앞 컷과 무엇이 달라졌는지(샷 크기·앵글·피사체)가 드러나게 쓴다.
  '앞 장면에서 이어지는 샷'으로 표시된 컷은 앞 구간 마지막 컷과 같은 샷이 계속되는 부분이다 (보이는 변화만 적는다).
- shot_type: 샷 크기.
- role: 광고 구성상 이 구간의 역할."""

OVERALL_SYSTEM = """당신은 한국 퍼포먼스 광고 기획자입니다.
레퍼런스 영상의 구간별 분석 결과를 보고 영상 전체의 말투, 컨셉, 화자 페르소나, 구성을 정리하세요.
이 결과는 자사 제품으로 같은 톤의 새 스크립트를 쓰는 데 사용됩니다. 모든 값은 한국어로 작성하세요.

- tone.speech_level: 존댓말 / 반말 / 혼용
- tone.pace: 말 속도와 리듬
- tone.habits: 반복되는 어미, 감탄사, 말버릇, 유행어 (예: "진짜", "~거든요")
- tone.description: 말투를 2~3문장으로 설명
- concept: 전체 컨셉, 소구 포인트, 스토리 전개 방식
- visual_style: 영상 전체의 비주얼 스타일 — 촬영 방식(셀카/UGC/스튜디오/거치), 화면 비율 사용, 주요 색감과 톤,
  편집 리듬(컷 전환 속도, 줌·전환 효과). 이미지 생성 시 모든 장면에 공통으로 적용할 기준이 된다.
- persona: 화자의 연령대, 성별, 캐릭터, 신뢰를 주는 근거(전문가/실사용자 등)
- structure: 역할별로 묶은 구간 흐름 (start/end는 초 단위)"""


def _detail_schema() -> dict:
    return strict_object({key: {"type": "string"} for key in SCENE_DETAIL})


def _vision_schema() -> dict:
    item = strict_object({
        "index": {"type": "integer"},
        "scene": {"type": "string"},
        "detail": _detail_schema(),
        "dialogue": {"type": "string"},
        "shot_type": {"type": "string", "enum": SHOT_TYPES},
        "role": {"type": "string", "enum": list(ROLES)},
        "cuts": {"type": "array", "items": strict_object({"n": {"type": "integer"}, "description": {"type": "string"}})},
    })
    return strict_object({"segments": {"type": "array", "items": item}})


def _overall_schema() -> dict:
    return strict_object({
        "tone": strict_object({
            "speech_level": {"type": "string"},
            "pace": {"type": "string"},
            "habits": {"type": "array", "items": {"type": "string"}},
            "description": {"type": "string"},
        }),
        "concept": {"type": "string"},
        "visual_style": {"type": "string"},
        "persona": strict_object({
            "age": {"type": "string"},
            "gender": {"type": "string"},
            "character": {"type": "string"},
            "credibility": {"type": "string"},
        }),
        "structure": {
            "type": "array",
            "items": strict_object({
                "role": {"type": "string", "enum": list(ROLES)},
                "start": {"type": "number"},
                "end": {"type": "number"},
                "summary": {"type": "string"},
            }),
        },
    })


def _analyze_batch(project_id: str, batch: list[Segment], transcript: str) -> None:
    ref_dir = store.reference_dir(project_id)
    content: list[dict] = [{"type": "text", "text": f"[영상 전체 대사 (맥락 참고용)]\n{transcript or '(대사 없음)'}"}]
    for seg in batch:
        content.append({
            "type": "text",
            "text": f"[구간 index={seg.index}] {fmt_time(seg.start)}–{fmt_time(seg.end)} · 컷 {len(seg.cuts)}개\n"
                    f"STT 대사: {seg.dialogue or '(없음)'}",
        })
        for n, cut in _shown_cuts(seg):
            note = " (앞 장면에서 이어지는 샷)" if cut.cont else ""
            content.append({"type": "text", "text": f"  컷 {n}: {cut.start:.1f}–{cut.end:.1f}초{note}"})
            content.append(claude_client.image_block(ref_dir / Path(cut.frame).relative_to("reference")))
    content.append({"type": "text", "text": f"위 {len(batch)}개 구간을 모두 분석하세요. index는 그대로 유지하세요."})

    result = claude_client.json_call(VISION_SYSTEM, [{"role": "user", "content": content}], _vision_schema())
    by_index = {r["index"]: r for r in result.get("segments", [])}
    for seg in batch:
        r = by_index.get(seg.index)
        if not r:
            continue
        seg.scene = r["scene"]
        seg.detail = SceneDetail.model_validate(r["detail"])
        seg.shot_type = r["shot_type"]
        seg.role = r["role"]
        descs = {c["n"]: c["description"] for c in r.get("cuts", [])}
        for n, cut in enumerate(seg.cuts, 1):
            cut.description = descs.get(n, "")
        # 교정본의 문장 수가 원본과 같을 때만 받아들인다 (문장 단위 보존)
        fixed = [line.strip() for line in r["dialogue"].splitlines() if line.strip()]
        if seg.dialogue and len(fixed) == len(seg.dialogue.splitlines()):
            seg.dialogue = "\n".join(fixed)


def _analyze_overall(segments: list[Segment]) -> Overall:
    lines = [
        f"#{s.index} {fmt_time(s.start)}–{fmt_time(s.end)} [{s.role}/{s.shot_type}] 장면: {s.scene}\n"
        f"{detail_text(s.detail, '    ')}\n    대사: {' / '.join(s.dialogue.splitlines()) or '-'}"
        for s in segments
    ]
    result = claude_client.json_call(
        OVERALL_SYSTEM,
        [{"role": "user", "content": "\n".join(lines)}],
        _overall_schema(),
    )
    return Overall.model_validate(result)


def _shown_cuts(seg: Segment) -> list[tuple[int, RefCut]]:
    """Claude에게 보여 줄 컷 (번호는 1부터). 너무 많으면 고르게 골라 MAX_CUT_FRAMES장까지."""
    numbered = list(enumerate(seg.cuts, 1))
    if len(numbered) <= MAX_CUT_FRAMES:
        return numbered
    step = (len(numbered) - 1) / (MAX_CUT_FRAMES - 1)
    return [numbered[round(i * step)] for i in range(MAX_CUT_FRAMES)]


def _add_cuts(src: Path, ref_dir: Path, segments: list[Segment], cut_times: list[float]) -> None:
    """구간마다 컷(화면 전환 기준)을 나누고 컷별 대표 프레임을 뽑는다.

    구간 첫 컷이 앞 구간 마지막 컷과 같은 샷이면(경계에서 화면이 안 바뀜) cont로 표시한다
    → 영상 제작 단계에서 이미지·영상을 새로 만들지 않고 앞 컷을 이어 쓴다.
    """
    jobs = []
    for i, seg in enumerate(segments):
        seg.cuts = []
        for k, (a, b, split) in enumerate(video_ingest.plan_cuts(seg.start, seg.end, cut_times)):
            cont = k == 0 and i > 0 and not video_ingest.has_cut_at(seg.start, cut_times)
            seg.cuts.append(RefCut(start=a, end=b, split=split, cont=cont, frame=f"reference/frames/cut_{seg.index:04d}_{k}.jpg"))
            jobs.append((seg.index, k, a + (b - a) / 2))
    video_ingest.extract_cut_frames(src, ref_dir / "frames", jobs)


# ── 파이프라인 ─────────────────────────────────────────────

def run_analysis(project_id: str) -> None:
    """백그라운드 스레드에서 실행된다. 진행 상황은 project.json의 analysis_job에 기록."""
    try:
        ref_dir = store.reference_dir(project_id)
        src = next(ref_dir.glob("source.*"))

        _set_job(project_id, "running", 0.02, "영상 정보 확인 중")
        info = video_ingest.probe(src)
        bounds = video_ingest.segment_bounds(info.duration)

        _set_job(project_id, "running", 0.05, f"프레임 추출 중 ({len(bounds)}개 구간)")
        frames_dir = ref_dir / "frames"
        for old in frames_dir.glob("*.jpg"):
            old.unlink()
        frame_paths = video_ingest.extract_frames(src, frames_dir, bounds)

        utterances: list[transcribe.Utterance] = []  # 문장 단위
        if info.has_audio:
            _set_job(project_id, "running", 0.15, "음성 인식 중 (첫 실행 시 모델 다운로드로 오래 걸릴 수 있음)")
            audio = ref_dir / "audio.wav"
            video_ingest.extract_audio(src, audio)
            utterances = transcribe.get_engine().transcribe(audio)
            store.write_json(ref_dir / "transcript.json", [u.__dict__ for u in utterances])

        _set_job(project_id, "running", 0.4, "화면 전환(컷) 감지 중")
        cut_times = video_ingest.detect_cuts(src)

        # 1초 구간에 문장 배정 → 같은 대사 / 같은 장면(대사 없음·화면 그대로) 구간 병합 → 각 문장은 한 구간에만 남김
        segments = [
            Segment(index=i, start=s, end=e, frames=[p.relative_to(ref_dir).as_posix()])
            for i, ((s, e), p) in enumerate(zip(bounds, frame_paths))
        ]
        ids = transcribe.assign_to_segments(utterances, bounds)
        segments, ids = merge_identical_dialogue(segments, ids, cut_times)
        ids = transcribe.keep_single_owner(utterances, [(s.start, s.end) for s in segments], ids)
        for seg, seg_ids in zip(segments, ids):
            seg.dialogue = "\n".join(utterances[u].text for u in seg_ids)  # 한 줄 = 한 문장
        segments = merge_silent_same_shot(segments, cut_times)

        _set_job(project_id, "running", 0.45, "컷별 프레임 추출 중")
        _add_cuts(src, ref_dir, segments, cut_times)

        source = SourceInfo(
            file=src.name,
            duration_sec=round(info.duration, 2),
            width=info.width,
            height=info.height,
            detected_aspect_ratio=video_ingest.closest_aspect_ratio(info.width, info.height),
        )

        if not claude_client.is_configured():
            for seg in segments:
                seg.scene = MOCK_NOTE
            overall = Overall(concept=MOCK_NOTE)
            mock = True
        else:
            transcript = "\n".join(f"{fmt_time(u.start)} {u.text}" for u in utterances)
            batches = [segments[i:i + VISION_BATCH] for i in range(0, len(segments), VISION_BATCH)]
            _set_job(project_id, "running", 0.5, f"장면 분석 중 (0/{len(batches)})")
            # 묶음끼리는 서로 독립이므로 동시에 요청해 긴 영상의 대기 시간을 줄인다
            with ThreadPoolExecutor(max_workers=VISION_PARALLEL) as pool:
                futures = [pool.submit(_analyze_batch, project_id, b, transcript) for b in batches]
                for n, fut in enumerate(as_completed(futures), 1):
                    fut.result()
                    _set_job(project_id, "running", 0.5 + 0.4 * n / len(batches), f"장면 분석 중 ({n}/{len(batches)})")
            _set_job(project_id, "running", 0.92, "말투·컨셉·페르소나 분석 중")
            overall = _analyze_overall(segments)
            mock = False

        store.save_analysis(project_id, ReferenceAnalysis(source=source, segments=segments, overall=overall, mock=mock))
        _set_job(project_id, "done", 1.0, "분석 완료")

        import gates  # 순환 import 방지
        spoken = [u.text for u in utterances]
        summary = [f"{fmt_time(source.duration_sec)} · {len(segments)}개 구간 · 대사 {len(spoken)}문장"]
        if spoken:
            summary.append(f"첫 대사: 「{spoken[0]}」")
        if overall.tone.speech_level:
            summary.append(f"말투: {overall.tone.speech_level} / 화자: {overall.persona.age} {overall.persona.gender}".strip())
        gates.open_gate(project_id, "analysis", "\n".join(summary))
    except Exception as e:  # noqa: BLE001 — 어떤 오류든 UI에 표시
        traceback.print_exc()
        _set_job(project_id, "error", 0, explain(e, "레퍼런스 분석"))
