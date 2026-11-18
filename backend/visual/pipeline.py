"""②-A 비주얼 파이프라인: 장면 브리프 → 장면 이미지 → (사람이 승인) → 장면 클립.

장면 브리프는 레퍼런스 장면 분석 + 자사 대사 + 제품 이미지로 이 단계에서 만든다 (briefs.py).
마음에 안 드는 장면만 다시 만든 뒤 [이미지 전체 승인]하면 영상화한다. 영상도 장면을 골라 그 장면만 다시 만들 수 있다.
"""
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
import gates
from planning import store
from schemas import JobState, Script, VisualAsset

from .briefs import ROLE_OTHER, ROLE_PACKAGING, build_briefs, product_image_entries, reference_for
from . import catalog
from .engine import HiggsfieldEngine, SceneContext, get_engine, portrait_prompt

PARALLEL = 3  # 동시에 생성할 장면 수 (힉스필드 계정 동시 처리 한도 안에서)


def _uses_catalog() -> bool:
    return isinstance(get_engine(), HiggsfieldEngine)


def image_model(project_id: str) -> str:
    chosen = store.get_production(project_id).visual.image_model
    return catalog.resolve("image", chosen) if _uses_catalog() else (chosen or config.HIGGSFIELD_IMAGE_MODEL)


def video_model(project_id: str) -> str:
    chosen = store.get_production(project_id).visual.video_model
    return catalog.resolve("video", chosen) if _uses_catalog() else (chosen or config.HIGGSFIELD_VIDEO_MODEL)


def _context(project_id: str, script: Script, scene_id: str) -> SceneContext:
    scene = next(s for s in script.scenes if s.id == scene_id)
    ref = reference_for(project_id, scene.ref_segment)
    ref_frame = store.project_dir(project_id) / ref["frames"][0] if ref and ref["frames"] else None
    visual = store.get_production(project_id).visual
    asset = visual.scenes.get(scene_id) or VisualAsset()
    roles = visual.product_roles
    products = [(path, roles.get(rel) or (ROLE_PACKAGING if rel.startswith("cutout/") else ROLE_OTHER))
                for rel, path in product_image_entries(project_id)]
    return SceneContext(
        scene=scene,
        aspect=script.meta.aspect_ratio,
        ref_frame=ref_frame,
        products=products,
        prompt=asset.prompt,
        motion=asset.motion,
        has_person=asset.has_person,
        cast_image=store.project_dir(project_id) / visual.cast_image if visual.cast_image else None,
        product_scale=visual.product_scale,
        image_model=image_model(project_id),
        video_model=video_model(project_id),
    )


def save_briefs(project_id: str, only_missing: bool = False) -> None:
    """장면 브리프 작성. only_missing이면 아직 브리프가 없는 장면이 있을 때만 (전체 흐름을 보고 함께 작성)."""
    scenes = store.get_production(project_id).visual.scenes
    if only_missing and all(scenes.get(s.id) and scenes[s.id].prompt for s in store.get_script(project_id).scenes):
        return
    briefs = build_briefs(project_id)
    with store.lock(project_id):
        prod = store.get_production(project_id)
        for sid, b in briefs.scenes.items():
            a = prod.visual.scenes.setdefault(sid, VisualAsset())
            if not (only_missing and a.prompt):
                a.prompt, a.motion, a.has_person = b["prompt"], b["motion"], b["has_person"]
        v = prod.visual
        if not (only_missing and v.character):
            if briefs.character != v.character:
                v.cast_image = None  # 인물 설정이 바뀌면 기준 이미지도 새로 만든다
            v.character = briefs.character
        if not (only_missing and v.product_scale):
            v.product_scale, v.product_roles = briefs.product_scale, briefs.product_roles
        store.save_production(project_id, prod)


def make_cast(project_id: str) -> None:
    """새 인물 기준 이미지를 만든다 (참고 이미지 없이 글로만 → 레퍼런스 인물을 닮지 않음)."""
    visual = store.get_production(project_id).visual
    if not visual.character:
        return
    engine = get_engine()
    rel = "visual/cast.jpg"
    engine.generate_portrait(portrait_prompt(visual.character), store.get_script(project_id).meta.aspect_ratio,
                             image_model(project_id), store.project_dir(project_id) / rel)
    with store.lock(project_id):
        prod = store.get_production(project_id)
        prod.visual.cast_image, prod.visual.cast_v = rel, int(time.time() * 1000)
        store.save_production(project_id, prod)


def set_approval(project_id: str, scene_ids: list[str] | None, approved: bool) -> None:
    """장면 이미지 승인/해제. scene_ids가 None이면 이미지가 있는 모든 장면."""
    with store.lock(project_id):
        prod = store.get_production(project_id)
        for sid, a in prod.visual.scenes.items():
            if a.image and (scene_ids is None or sid in scene_ids):
                a.image_approved = approved
        store.save_production(project_id, prod)


def approved_without_video(project_id: str) -> list[str]:
    scenes = store.get_production(project_id).visual.scenes
    return [s.id for s in store.get_script(project_id).scenes
            if scenes.get(s.id) and scenes[s.id].image_approved and not scenes[s.id].video]


def make_image(project_id: str, scene_id: str) -> None:
    script = store.get_script(project_id)
    engine = get_engine()
    ctx = _context(project_id, script, scene_id)
    rel = f"visual/{scene_id}.jpg"
    # 브리프는 유지하고 이미지가 바뀌면 기존 영상은 무효
    asset = VisualAsset(prompt=ctx.prompt, motion=ctx.motion, has_person=ctx.has_person, v=int(time.time() * 1000))
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
    if not asset.image_approved:
        raise ValueError(f"{scene_id} 장면 이미지를 먼저 승인하세요.")
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
    """장면별 생성을 PARALLEL개씩 동시에 돌린다. 장면 하나의 실패는 그 장면의 error에 남고 전체는 계속된다."""
    try:
        total = len(scene_ids)
        store.update_project(project_id, visual_job=JobState(status="running", progress=0, message=f"{label} (0/{total})"))
        with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
            futures = [pool.submit(fn, project_id, sid) for sid in scene_ids]
            for n, fut in enumerate(as_completed(futures), 1):
                fut.result()
                store.update_project(project_id, visual_job=JobState(status="running", progress=n / total, message=f"{label} ({n}/{total})"))
        failed = _failed(project_id, scene_ids, "video" if fn is make_video else "image")
        msg = f"{label} 완료" + (f" · 실패 {failed}개 (장면별 ↻로 다시 시도)" if failed else "")
        store.update_project(project_id, visual_job=JobState(status="done", progress=1, message=msg))
        return True
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        store.update_project(project_id, visual_job=JobState(status="error", message=str(e)))
        return False


def _failed(project_id: str, scene_ids: list[str], what: str) -> int:
    scenes = store.get_production(project_id).visual.scenes
    return sum(1 for sid in scene_ids if not (scenes.get(sid) and getattr(scenes[sid], what)))


def run_images(project_id: str, scene_ids: list[str] | None = None) -> None:
    """scene_ids가 없으면 전체(브리프 새로 작성), 있으면 그 장면만 다시 만든다(기존 브리프 유지)."""
    script = store.get_script(project_id)
    ids = scene_ids or [s.id for s in script.scenes]
    try:
        store.update_project(project_id, visual_job=JobState(status="running", progress=0, message="장면 브리프 작성 중 (장면 분석 + 자사 대사 + 제품 이미지)"))
        save_briefs(project_id, only_missing=bool(scene_ids))
        if not store.get_production(project_id).visual.cast_image:
            store.update_project(project_id, visual_job=JobState(status="running", progress=0, message="새 인물 만드는 중 (레퍼런스 인물과 다른 얼굴·헤어·의상)"))
            make_cast(project_id)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        store.update_project(project_id, visual_job=JobState(status="error", message=f"장면 브리프·인물 준비 실패: {e}"))
        return
    if not _run(project_id, "장면 이미지 생성", make_image, ids):
        return
    prod = store.get_production(project_id)
    ok = sum(1 for sid in ids if prod.visual.scenes.get(sid) and prod.visual.scenes[sid].image)
    if not scene_ids:
        gates.open_gate(project_id, "images", f"장면 이미지 {ok}/{len(ids)}장 생성 · 전체 승인하면 영상화를 시작합니다 · 엔진: {prod.visual.engine}")


def run_videos(project_id: str, scene_ids: list[str] | None = None) -> None:
    """scene_ids가 없으면 '승인됐지만 아직 영상이 없는 장면'을 영상화한다."""
    from workflow import maybe_open_production_gate  # 순환 import 방지

    ids = scene_ids or approved_without_video(project_id)
    if _run(project_id, "장면 영상화", make_video, ids):
        maybe_open_production_gate(project_id)
