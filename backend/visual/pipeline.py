"""②-A 비주얼 파이프라인: 장면 브리프 → 장면 이미지 → 장면 클립.

장면 브리프는 레퍼런스 장면 분석 + 자사 대사 + 제품 이미지로 이 단계에서 만든다 (briefs.py).
"""
import time
import traceback

import gates
from planning import store
from schemas import JobState, Script, VisualAsset

from .briefs import build_briefs, product_images, reference_for
from .engine import SceneContext, get_engine


def _context(project_id: str, script: Script, scene_id: str) -> SceneContext:
    scene = next(s for s in script.scenes if s.id == scene_id)
    ref = reference_for(project_id, scene.ref_segment)
    ref_frame = store.project_dir(project_id) / ref["frames"][0] if ref and ref["frames"] else None
    asset = store.get_production(project_id).visual.scenes.get(scene_id) or VisualAsset()
    return SceneContext(
        scene=scene,
        aspect=script.meta.aspect_ratio,
        ref_frame=ref_frame,
        product_images=product_images(project_id),
        prompt=asset.prompt,
        motion=asset.motion,
    )


def save_briefs(project_id: str) -> None:
    briefs = build_briefs(project_id)
    with store.lock(project_id):
        prod = store.get_production(project_id)
        for sid, b in briefs.items():
            a = prod.visual.scenes.setdefault(sid, VisualAsset())
            a.prompt, a.motion = b["prompt"], b["motion"]
        store.save_production(project_id, prod)


def make_image(project_id: str, scene_id: str) -> None:
    script = store.get_script(project_id)
    engine = get_engine()
    ctx = _context(project_id, script, scene_id)
    rel = f"visual/{scene_id}.jpg"
    # 브리프는 유지하고 이미지가 바뀌면 기존 영상은 무효
    asset = VisualAsset(prompt=ctx.prompt, motion=ctx.motion, v=int(time.time() * 1000))
    try:
        engine.generate_image(ctx, store.project_dir(project_id) / rel)
        asset.image = rel
    except Exception as e:  # noqa: BLE001
        asset.error = str(e)
    with store.lock(project_id):
        prod = store.get_production(project_id)
        prod.visual.engine = engine.label
        prod.visual.scenes[scene_id] = asset
        store.save_production(project_id, prod)


def make_video(project_id: str, scene_id: str) -> None:
    script = store.get_script(project_id)
    asset = store.get_production(project_id).visual.scenes.get(scene_id)
    if not asset or not asset.image:
        raise ValueError(f"{scene_id} 장면 이미지가 없습니다.")
    engine = get_engine()
    ctx = _context(project_id, script, scene_id)
    rel = f"visual/{scene_id}.mp4"
    error = ""
    try:
        engine.animate(store.project_dir(project_id) / asset.image, ctx, store.project_dir(project_id) / rel)
    except Exception as e:  # noqa: BLE001
        error = str(e)
    with store.lock(project_id):
        prod = store.get_production(project_id)
        a = prod.visual.scenes[scene_id]
        a.video, a.error, a.v = (None if error else rel), error, int(time.time() * 1000)
        store.save_production(project_id, prod)


def _run(project_id: str, label: str, fn, scene_ids: list[str]) -> bool:
    try:
        for n, sid in enumerate(scene_ids):
            store.update_project(project_id, visual_job=JobState(status="running", progress=n / len(scene_ids), message=f"{label} ({n + 1}/{len(scene_ids)})"))
            fn(project_id, sid)
        store.update_project(project_id, visual_job=JobState(status="done", progress=1, message=f"{label} 완료"))
        return True
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        store.update_project(project_id, visual_job=JobState(status="error", message=str(e)))
        return False


def run_images(project_id: str) -> None:
    script = store.get_script(project_id)
    ids = [s.id for s in script.scenes]
    try:
        store.update_project(project_id, visual_job=JobState(status="running", progress=0, message="장면 브리프 작성 중 (장면 분석 + 자사 대사 + 제품 이미지)"))
        save_briefs(project_id)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        store.update_project(project_id, visual_job=JobState(status="error", message=f"장면 브리프 작성 실패: {e}"))
        return
    if not _run(project_id, "장면 이미지 생성", make_image, ids):
        return
    prod = store.get_production(project_id)
    ok = sum(1 for sid in ids if prod.visual.scenes.get(sid) and prod.visual.scenes[sid].image)
    gates.open_gate(project_id, "images", f"장면 이미지 {ok}/{len(ids)}장 생성 · 엔진: {prod.visual.engine}")


def run_videos(project_id: str) -> None:
    from workflow import maybe_open_production_gate  # 순환 import 방지

    script = store.get_script(project_id)
    if _run(project_id, "장면 영상화", make_video, [s.id for s in script.scenes]):
        maybe_open_production_gate(project_id)
