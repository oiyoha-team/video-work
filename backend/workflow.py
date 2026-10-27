"""단계 전환 규칙. '진행'이 무엇을 실행하는지는 모두 여기서 정한다.

화면의 [진행] 버튼, 알림 센터의 [진행], Flow 메신저의 「진행」이 모두 이 함수들을 호출한다.

  1 레퍼런스 분석 ─(analysis 게이트)→ 2 제품 정보 → 3 스크립트 ─(script 게이트)→ 4 기획 확정
  → 5 영상 제작: 비주얼(이미지 ─(images 게이트)→ 영상화) ∥ 사운드(TTS)
  ─(production 게이트)→ 6 결과물 다운로드 (사용자가 직접 편집)
"""
import threading
import traceback

import gates
from llm import claude_client
from planning import analyze, chat_agent, script_writer, store
from schemas import JobState, Project
from sound import pipeline as sound_pipeline
from visual import pipeline as visual_pipeline


def start(target, project_id: str) -> None:
    threading.Thread(target=target, args=(project_id,), daemon=True).start()


def _advance(project_id: str, step: int) -> Project:
    project = store.get_project(project_id)
    return store.update_project(project_id, step=max(project.step, step))


def _ensure_idle(project: Project, field: str, label: str) -> None:
    if getattr(project, field).status == "running":
        raise ValueError(f"{label}이(가) 이미 진행 중입니다.")


# ── 1 → 2 ─────────────────────────────────────────────

def start_analysis(project_id: str) -> None:
    store.update_project(project_id, analysis_job=JobState(status="running", message="분석 대기 중"))
    start(analyze.run_analysis, project_id)


def confirm_analysis(project_id: str) -> Project:
    analysis = store.get_analysis(project_id)
    if analysis is None:
        raise ValueError("분석 결과가 없습니다.")
    analysis.confirmed = True
    store.save_analysis(project_id, analysis)
    gates.close_kind(project_id, "analysis")
    return _advance(project_id, 2)


# ── 2 → 3 ─────────────────────────────────────────────

def start_script(project_id: str) -> None:
    store.update_project(project_id, script_job=JobState(status="running", message="스크립트 작성 대기 중"))
    start(script_writer.run_generate, project_id)


def confirm_product(project_id: str) -> Project:
    product = store.get_product(project_id)
    if not product.name.strip():
        raise ValueError("제품명을 입력하세요.")
    if not product.usp.strip():
        raise ValueError("제품 USP를 입력하세요.")
    project = _advance(project_id, 3)
    if store.get_script(project_id) is None and project.script_job.status != "running":
        start_script(project_id)
    return store.get_project(project_id)


# ── 3 → 4 ─────────────────────────────────────────────

def finalize_script(project_id: str) -> Project:
    script = store.get_script(project_id)
    if script is None:
        raise ValueError("스크립트가 없습니다.")
    script.status = "final"
    store.save_script(project_id, script)
    text = script_writer.to_text(script)
    (store.project_dir(project_id) / "script.txt").write_text(text, encoding="utf-8")
    gates.close_kind(project_id, "script")
    return _advance(project_id, 4)


def revise_script_remotely(project_id: str, comment: str) -> None:
    """원격(Flow) 수정 요청: Claude가 코멘트대로 고친 뒤 수정본으로 다시 승인을 요청한다."""
    try:
        store.update_project(project_id, script_job=JobState(status="running", progress=0.3, message="수정 요청 반영 중"))
        history = chat_agent.send(project_id, comment)
        last = history[-1]
        if last.get("status") == "pending":
            chat_agent.resolve(project_id, last["id"], apply=True)
        store.update_project(project_id, script_job=JobState(status="done", progress=1, message="수정 반영 완료"))
        gates.open_gate(project_id, "script", f"요청: {comment}\n반영: {last.get('content', '')}", title="수정본 작성 완료 — 기획안을 확정할까요?")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        store.update_project(project_id, script_job=JobState(status="error", message=str(e)))


# ── 4 → 5 (영상 제작: 비주얼 ∥ 사운드) ─────────────────────────────────────────────

def start_production(project_id: str) -> Project:
    script = store.get_script(project_id)
    if script is None or script.status != "final":
        raise ValueError("기획안을 먼저 확정하세요.")
    project = _advance(project_id, 5)
    prod = store.get_production(project_id)
    # 처음 들어온 경우 두 트랙을 동시에 시작
    if not prod.visual.scenes and project.visual_job.status != "running":
        start_images(project_id)
    if not prod.sound.scenes and project.sound_job.status != "running":
        start_sound(project_id)
    return store.get_project(project_id)


def start_images(project_id: str) -> None:
    _ensure_idle(store.get_project(project_id), "visual_job", "비주얼 작업")
    store.update_project(project_id, visual_job=JobState(status="running", message="이미지 생성 대기 중"))
    start(visual_pipeline.run_images, project_id)


def start_videos(project_id: str) -> None:
    _ensure_idle(store.get_project(project_id), "visual_job", "비주얼 작업")
    gates.close_kind(project_id, "images")
    store.update_project(project_id, visual_job=JobState(status="running", message="영상화 대기 중"))
    start(visual_pipeline.run_videos, project_id)


def start_sound(project_id: str) -> None:
    _ensure_idle(store.get_project(project_id), "sound_job", "음성 작업")
    store.update_project(project_id, sound_job=JobState(status="running", message="음성 생성 대기 중"))
    start(sound_pipeline.run_sound, project_id)


def production_status(project_id: str) -> dict:
    script = store.get_script(project_id)
    prod = store.get_production(project_id)
    ids = [s.id for s in script.scenes] if script else []
    videos = sum(1 for i in ids if prod.visual.scenes.get(i) and prod.visual.scenes[i].video)
    audios = sum(1 for i in ids if i in prod.sound.scenes)
    return {"total": len(ids), "videos": videos, "audios": audios, "ready": bool(ids) and videos == len(ids) and audios == len(ids)}


def maybe_open_production_gate(project_id: str) -> None:
    """비주얼·사운드 두 트랙이 모두 끝났을 때만 합성 승인을 요청한다."""
    st = production_status(project_id)
    project = store.get_project(project_id)
    if st["ready"] and "running" not in (project.visual_job.status, project.sound_job.status):
        gates.open_gate(project_id, "production", f"영상 클립 {st['videos']}개 · 음성 {st['audios']}개 준비 완료")


# ── 5 → 6 결과물 다운로드 ─────────────────────────────────────────────

def confirm_production(project_id: str) -> Project:
    """영상 제작 확정. 이후에는 결과물을 내려받아 사용자가 직접 편집한다."""
    if not production_status(project_id)["ready"]:
        raise ValueError("모든 장면의 영상 클립과 음성이 준비되어야 합니다.")
    gates.close_kind(project_id, "production")
    _advance(project_id, 6)
    return store.update_project(project_id, completed=True)


# ── 승인 게이트 처리 (앱 알림 센터 / Flow 공통) ─────────────────────────────────────────────

APPROVE = {
    "analysis": confirm_analysis,
    "script": finalize_script,
    "images": start_videos,
    "production": confirm_production,
}


def resolve_gate(project_id: str, gate_id: str, action: str, comment: str = "", via: str = "ui") -> dict:
    gate = gates.get_pending(project_id, gate_id)
    if action == "approve":
        APPROVE[gate.kind](project_id)
        gates.mark(project_id, gate_id, "approved", via, comment)
        return {"result": "approved", "kind": gate.kind}
    if action == "revise":
        gates.mark(project_id, gate_id, "revised", via, comment)
        if gate.kind == "script" and comment and claude_client.is_configured():
            start(lambda pid: revise_script_remotely(pid, comment), project_id)
            return {"result": "revising", "kind": gate.kind}
        return {"result": "revised", "kind": gate.kind}
    raise ValueError("action은 approve 또는 revise 여야 합니다.")
