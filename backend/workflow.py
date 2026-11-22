"""단계 전환 규칙. '진행'이 무엇을 실행하는지는 모두 여기서 정한다.

화면의 [진행] 버튼, 알림 센터의 [진행], Flow 메신저의 「진행」이 모두 이 함수들을 호출한다.

  1 레퍼런스 분석 ─(analysis 게이트)→ 2 제품 정보 → 3 스크립트 ─(script 게이트)→ 4 기획 확정
  → 5 영상 제작: 비주얼(이미지 ─(images 게이트)→ 영상화) ∥ 사운드(TTS)
  ─(production 게이트)→ 6 결과물 다운로드 (사용자가 직접 편집)
"""
import shutil
import threading
import traceback

import gates
from errors import explain
from llm import claude_client
from planning import analyze, chat_agent, script_writer, store
from schemas import JobState, Product, Project
from sound import pipeline as sound_pipeline
from visual import pipeline as visual_pipeline


def start(target, project_id: str, *args) -> None:
    threading.Thread(target=target, args=(project_id, *args), daemon=True).start()


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
        store.update_project(project_id, script_job=JobState(status="error", message=explain(e, "수정 요청 반영")))


# ── 4 → 5 (영상 제작: 비주얼 ∥ 사운드) ─────────────────────────────────────────────

def start_production(project_id: str) -> Project:
    script = store.get_script(project_id)
    if script is None or script.status != "final":
        raise ValueError("기획안을 먼저 확정하세요.")
    # 자동으로 시작하지 않는다: 이미지는 예상 비용을 보고, 음성은 목소리·배속을 고른 뒤 화면에서 직접 시작한다
    _advance(project_id, 5)
    return store.get_project(project_id)


def start_images(project_id: str, scene_ids: list[str] | None = None, instruction: str = "") -> None:
    """instruction: 사용자가 입력한 수정 지시 (선택한 장면 모두에 반영)."""
    _ensure_idle(store.get_project(project_id), "visual_job", "비주얼 작업")
    store.update_project(project_id, visual_job=JobState(status="running", message="이미지 생성 준비 중"))
    start(visual_pipeline.run_images, project_id, scene_ids, instruction.strip())


def start_cast(project_id: str) -> None:
    _ensure_idle(store.get_project(project_id), "visual_job", "비주얼 작업")
    if not store.get_production(project_id).visual.character:
        raise ValueError("아직 인물 설정이 없습니다. 이미지를 먼저 생성하세요.")
    if visual_pipeline.anchor_has_person(project_id):
        raise ValueError("인물은 첫 장면(기준 장면)을 그대로 씁니다. 인물을 바꾸려면 첫 장면 이미지를 다시 만드세요.")
    store.update_project(project_id, visual_job=JobState(status="running", message="인물 기준 이미지 준비 중"))
    start(visual_pipeline.run_cast, project_id)


def start_videos(project_id: str, scene_ids: list[str] | None = None, instruction: str = "") -> None:
    """승인된 이미지만 영상화한다. scene_ids가 없으면 '승인됐지만 아직 영상이 없는 장면' 전부."""
    _ensure_idle(store.get_project(project_id), "visual_job", "비주얼 작업")
    scenes = store.get_production(project_id).visual.scenes
    if scene_ids:
        bad = [s for s in scene_ids if not (scenes.get(s) and scenes[s].image_approved)]
        if bad:
            raise ValueError(f"이미지를 먼저 승인하세요: {', '.join(bad)}")
    elif not visual_pipeline.approved_without_video(project_id):
        raise ValueError("영상화할 장면이 없습니다. 이미지를 먼저 승인하세요.")
    gates.close_kind(project_id, "images")
    store.update_project(project_id, visual_job=JobState(status="running", message="영상화 준비 중"))
    start(visual_pipeline.run_videos, project_id, scene_ids, instruction.strip())


def approve_images_and_animate(project_id: str) -> None:
    """[이미지 전체 승인]: 모든 이미지를 승인하고, 아직 영상이 없는 장면을 영상화한다 (화면·알림 센터·Flow 공통)."""
    st = production_status(project_id)
    if st["images"] < st["total"]:
        raise ValueError("모든 장면의 이미지가 있어야 전체 승인할 수 있습니다.")
    _ensure_idle(store.get_project(project_id), "visual_job", "비주얼 작업")
    visual_pipeline.keep_all_new(project_id)  # 이전/새 결과를 고르지 않은 장면은 새 결과로 확정
    visual_pipeline.set_approval(project_id, None, True)
    if visual_pipeline.approved_without_video(project_id):
        start_videos(project_id)
    else:
        gates.close_kind(project_id, "images")


def start_sound(project_id: str, scene_ids: list[str] | None = None) -> None:
    _ensure_idle(store.get_project(project_id), "sound_job", "음성 작업")
    store.update_project(project_id, sound_job=JobState(status="running", message="음성 생성 준비 중"))
    start(sound_pipeline.run_sound, project_id, scene_ids)


def production_status(project_id: str) -> dict:
    script = store.get_script(project_id)
    prod = store.get_production(project_id)
    ids = [s.id for s in script.scenes] if script else []
    vs = [prod.visual.scenes.get(i) for i in ids]
    ss = [prod.sound.scenes.get(i) for i in ids]
    st = {
        "total": len(ids),
        "images": sum(1 for a in vs if a and a.image),
        "images_approved": sum(1 for a in vs if a and a.image and a.image_approved),
        "videos": sum(1 for a in vs if a and a.video),
        "audios": sum(1 for a in ss if a and a.v),  # v=0은 아직 만드는 중(자리만 있음)
        "lines": sum(len(a.lines) for a in ss if a),
        "comparing": sum(1 for a in vs if a and a.prev),  # 이전/새 결과를 아직 고르지 않은 장면
    }
    # 영상·음성이 모두 있으면 [전체 승인]으로 다음 단계(결과물 받기)로 넘어갈 수 있다
    st["ready"] = bool(ids) and st["videos"] == len(ids) and st["audios"] == len(ids)
    return st


def maybe_open_production_gate(project_id: str) -> None:
    """비주얼·사운드 두 트랙이 모두 끝났을 때만 합성 승인을 요청한다."""
    st = production_status(project_id)
    project = store.get_project(project_id)
    if st["ready"] and "running" not in (project.visual_job.status, project.sound_job.status):
        gates.open_gate(project_id, "production", f"영상 클립 {st['videos']}개 · 음성 {st['lines']}문장 준비 완료")


# ── 초기화 ─────────────────────────────────────────────

def _ensure_no_jobs(project: Project) -> None:
    running = [f for f in Project.JOB_FIELDS if getattr(project, f).status == "running"]
    if running:
        raise ValueError("진행 중인 작업이 끝난 뒤 초기화할 수 있습니다.")


def reset_production(project_id: str, what: str) -> Project:
    """5단계 초기화. what: visual(이미지·영상) | sound(음성) | all. 고른 모델·목소리·배속은 남긴다."""
    if what not in ("visual", "sound", "all"):
        raise ValueError("what은 visual, sound, all 중 하나여야 합니다.")
    _ensure_no_jobs(store.get_project(project_id))
    changes: dict = {"completed": False}
    if what in ("visual", "all"):
        visual_pipeline.reset(project_id)
        gates.close_kind(project_id, "images")
        changes["visual_job"] = JobState()
    if what in ("sound", "all"):
        sound_pipeline.reset(project_id)
        changes["sound_job"] = JobState()
    gates.close_kind(project_id, "production")
    project = store.get_project(project_id)
    if project.step > 5:
        changes["step"] = 5
    return store.update_project(project_id, **changes)


def reset_project(project_id: str, keep_product: bool = True) -> Project:
    """프로젝트 전체 초기화: 이름만 남기고 1단계부터 다시. keep_product면 2단계 제품 정보·사진은 남긴다."""
    project = store.get_project(project_id)
    _ensure_no_jobs(project)
    for kind in ("analysis", "script", "images", "production"):
        gates.close_kind(project_id, kind)
    pdir = store.project_dir(project_id)
    for child in pdir.iterdir():
        if child.name == "project.json" or (keep_product and child.name == "product"):
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
    if not keep_product:
        store.save_product(project_id, Product())
    fresh = Project(id=project.id, name=project.name, created_at=project.created_at, updated_at=project.updated_at)
    return store.save_project(fresh)


# ── 5 → 6 결과물 다운로드 ─────────────────────────────────────────────

def confirm_production(project_id: str) -> Project:
    """영상 제작 확정. 이후에는 결과물을 내려받아 사용자가 직접 편집한다."""
    # 진행 상황과 상관없이 넘어갈 수 있다 (크레딧 절감: 이미지만 / 음성만 받고 끝내는 경우).
    # 없는 파일은 다운로드 목록에 나오지 않고, 나중에 5단계로 돌아와 이어서 만들 수 있다.
    project = store.get_project(project_id)
    if "running" in (project.visual_job.status, project.sound_job.status):
        raise ValueError("진행 중인 작업이 끝난 뒤 넘어갈 수 있습니다.")
    gates.close_kind(project_id, "production")
    _advance(project_id, 6)
    return store.update_project(project_id, completed=True)


# ── 승인 게이트 처리 (앱 알림 센터 / Flow 공통) ─────────────────────────────────────────────

APPROVE = {
    "analysis": confirm_analysis,
    "script": finalize_script,
    "images": approve_images_and_animate,
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
