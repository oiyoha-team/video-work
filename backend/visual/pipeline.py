"""②-A 비주얼 파이프라인: 장면 설계 → 기준 장면(첫 장면) → 나머지 장면 → (사람이 승인) → 장면 클립.

1. 장면 설계 (briefs.py): 레퍼런스의 그림체·페르소나·컨셉·후킹·전개 구성만 빌려 새 장면을 설계한다.
2. 기준 장면: 첫 장면을 레퍼런스 그림체 견본 + 제품 사진으로 먼저 만든다 (레퍼런스 장면을 그대로 넘기지 않음).
3. 나머지 장면: 기준 장면 이미지(그림체·세계관·인물) + 제품 사진을 참고해 일관되게 만든다.
4. 마음에 안 드는 장면만 (수정 지시와 함께) 다시 만들고, 이전/새 결과 중 고른 뒤 [이미지 전체 승인]하면 영상화한다.
"""
import shutil
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
import gates
import timings
from errors import explain
from planning import store
from schemas import JobState, Script, VisualAsset, VisualTrack, VisualVersion

from . import catalog
from .briefs import (ROLE_OTHER, ROLE_PACKAGING, build_briefs, product_image_entries, reference_for, revise_image_prompt,
                     revise_video_prompt, style_frames)
from .engine import HiggsfieldEngine, SceneContext, get_engine, portrait_prompt

PARALLEL = 3  # 동시에 생성할 장면 수 (힉스필드 계정 동시 처리 한도 안에서)
CAST_REL = "visual/cast.jpg"
_ANCHOR_STYLE_NOTE = ("the KEY FRAME of this ad. Draw the character in exactly this image's art style, rendering, "
                      "color palette and lighting mood.")


def _ms() -> int:
    return int(time.time() * 1000)


def _uses_catalog() -> bool:
    return isinstance(get_engine(), HiggsfieldEngine)


def image_model(project_id: str) -> str:
    chosen = store.get_production(project_id).visual.image_model
    return catalog.resolve("image", chosen) if _uses_catalog() else (chosen or config.HIGGSFIELD_IMAGE_MODEL)


def video_model(project_id: str) -> str:
    chosen = store.get_production(project_id).visual.video_model
    return catalog.resolve("video", chosen) if _uses_catalog() else (chosen or config.HIGGSFIELD_VIDEO_MODEL)


def anchor_id(project_id: str, script: Script | None = None) -> str:
    script = script or store.get_script(project_id)
    return store.get_production(project_id).visual.anchor_scene or (script.scenes[0].id if script and script.scenes else "")


def _context(project_id: str, script: Script, scene_id: str) -> SceneContext:
    pdir = store.project_dir(project_id)
    scene = next(s for s in script.scenes if s.id == scene_id)
    ref = reference_for(project_id, scene.ref_segment)
    visual = store.get_production(project_id).visual
    asset = visual.scenes.get(scene_id) or VisualAsset()
    roles = visual.product_roles
    products = [(path, roles.get(rel) or (ROLE_PACKAGING if rel.startswith("cutout/") else ROLE_OTHER))
                for rel, path in product_image_entries(project_id)]
    anchor = anchor_id(project_id, script)
    anchor_asset = visual.scenes.get(anchor)
    anchor_image = pdir / anchor_asset.image if scene_id != anchor and anchor_asset and anchor_asset.image else None
    return SceneContext(
        scene=scene,
        aspect=script.meta.aspect_ratio,
        ref_frame=pdir / ref["frames"][0] if ref and ref["frames"] else None,  # 임시 엔진 전용
        products=products,
        prompt=asset.prompt,
        motion=asset.motion,
        has_person=asset.has_person,
        cast_image=pdir / visual.cast_image if visual.cast_image else None,
        cast_is_anchor=bool(anchor_asset and anchor_asset.has_person),
        product_scale=visual.product_scale,
        image_model=image_model(project_id),
        video_model=video_model(project_id),
        style_guide=visual.style_guide,
        world=visual.world,
        style_frames=[] if anchor_image else style_frames(project_id, scene.ref_segment),
        anchor_image=anchor_image,
        video_prompt=asset.video_prompt,
    )


# ── 진행 표시 ─────────────────────────────────────────────

def _job(project_id: str, message: str, started: float, eta: tuple[float, float] | None, done: int = 0, total: int = 0) -> None:
    store.update_project(project_id, visual_job=JobState(
        status="running", message=message, progress=(done / total) if total else 0, started_at=started,
        eta_min=eta[0] if eta else None, eta_max=eta[1] if eta else None, eta_at=time.time(), done=done, total=total))


def _set_busy(project_id: str, scene_ids: list[str], state: str, only_if: str | None = None) -> None:
    with store.lock(project_id):
        prod = store.get_production(project_id)
        for sid in scene_ids:
            a = prod.visual.scenes.setdefault(sid, VisualAsset())
            if only_if is None or a.busy == only_if:
                a.busy, a.busy_since = state, time.time() if state else 0
        store.save_production(project_id, prod)


def clear_busy(project_id: str) -> None:
    """서버가 재시작돼 중단된 작업의 진행 표시를 지운다."""
    with store.lock(project_id):
        prod = store.get_production(project_id)
        if any(a.busy for a in prod.visual.scenes.values()):
            for a in prod.visual.scenes.values():
                a.busy, a.busy_since = "", 0
            store.save_production(project_id, prod)


# ── 장면 설계 · 인물 ─────────────────────────────────────────────

def save_briefs(project_id: str, only_missing: bool = False) -> None:
    """장면 설계. only_missing이면 아직 설계가 없는 장면이 있을 때만 (전체 흐름을 보고 함께 작성)."""
    script = store.get_script(project_id)
    scenes = store.get_production(project_id).visual.scenes
    if only_missing and all(scenes.get(s.id) and scenes[s.id].prompt for s in script.scenes):
        return
    briefs = build_briefs(project_id)
    with store.lock(project_id):
        prod = store.get_production(project_id)
        for sid, b in briefs.scenes.items():
            a = prod.visual.scenes.setdefault(sid, VisualAsset())
            if not (only_missing and a.prompt):
                a.prompt, a.motion, a.has_person, a.video_prompt = b["prompt"], b["motion"], b["has_person"], ""
        v = prod.visual
        if not (only_missing and v.style_guide):
            v.style_guide, v.world, v.concept_note = briefs.style_guide, briefs.world, briefs.concept_note
            v.anchor_scene = script.scenes[0].id if script.scenes else ""
        if not (only_missing and v.character):
            if briefs.character != v.character:
                v.cast_image = None  # 인물 설정이 바뀌면 기준 이미지도 새로 만든다
            v.character = briefs.character
        if not (only_missing and v.product_scale):
            v.product_scale, v.product_roles = briefs.product_scale, briefs.product_roles
        store.save_production(project_id, prod)


def _sync_cast_from_anchor(project_id: str) -> None:
    """기준 장면에 인물이 있으면 그 장면을 인물 기준 이미지로 쓴다 (따로 인물을 만들지 않음)."""
    pdir = store.project_dir(project_id)
    with store.lock(project_id):
        prod = store.get_production(project_id)
        a = prod.visual.scenes.get(anchor_id(project_id))
        if not (a and a.image and a.has_person and (pdir / a.image).exists()):
            return
        shutil.copyfile(pdir / a.image, pdir / CAST_REL)
        prod.visual.cast_image, prod.visual.cast_v = CAST_REL, _ms()
        store.save_production(project_id, prod)


def anchor_has_person(project_id: str) -> bool:
    a = store.get_production(project_id).visual.scenes.get(anchor_id(project_id))
    return bool(a and a.has_person)


def make_cast(project_id: str) -> None:
    """기준 장면에 인물이 없을 때: 기준 장면의 그림체로 새 인물 기준 이미지를 만든다 (레퍼런스 인물은 넣지 않음)."""
    visual = store.get_production(project_id).visual
    if not visual.character:
        return
    if anchor_has_person(project_id):
        _sync_cast_from_anchor(project_id)
        return
    pdir = store.project_dir(project_id)
    anchor = visual.scenes.get(anchor_id(project_id))
    refs = [(pdir / anchor.image, _ANCHOR_STYLE_NOTE)] if anchor and anchor.image and (pdir / anchor.image).exists() else []
    t = timings.Timer()
    model = image_model(project_id)
    get_engine().generate_portrait(portrait_prompt(visual.character, visual.style_guide), store.get_script(project_id).meta.aspect_ratio,
                                   model, pdir / CAST_REL, refs)
    timings.record("portrait", t.seconds, model)
    with store.lock(project_id):
        prod = store.get_production(project_id)
        prod.visual.cast_image, prod.visual.cast_v = CAST_REL, _ms()
        store.save_production(project_id, prod)


# ── 승인 · 이전/새 결과 고르기 ─────────────────────────────────────────────

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


def _delete_unused(project_id: str, old: VisualVersion | VisualAsset | None, keep: VisualAsset | VisualVersion | None) -> None:
    """old의 파일 중 keep(지금 쓰는 결과)이 쓰지 않는 것을 지운다."""
    if not old:
        return
    pdir = store.project_dir(project_id)
    used = {keep.image, keep.video, CAST_REL} if keep else {CAST_REL}
    for rel in (old.image, old.video):
        if rel and rel not in used:
            (pdir / rel).unlink(missing_ok=True)


def _snapshot(a: VisualAsset) -> VisualVersion:
    return VisualVersion(image=a.image, video=a.video, prompt=a.prompt, motion=a.motion, video_prompt=a.video_prompt,
                         image_approved=a.image_approved, instruction=a.instruction, v=a.v)


def choose_version(project_id: str, scene_id: str, keep: str) -> None:
    """다시 만든 장면에서 이전 결과(prev)와 새 결과 중 하나를 고른다."""
    with store.lock(project_id):
        prod = store.get_production(project_id)
        a = prod.visual.scenes.get(scene_id)
        if not a or not a.prev:
            raise ValueError("비교할 이전 결과가 없습니다.")
        if keep == "prev":
            p = a.prev
            restored = VisualAsset(prompt=p.prompt, motion=p.motion, video_prompt=p.video_prompt, image=p.image, video=p.video,
                                   has_person=a.has_person, image_approved=p.image_approved, instruction=p.instruction, v=_ms())
            _delete_unused(project_id, a, restored)
            prod.visual.scenes[scene_id] = restored
        elif keep == "new":
            _delete_unused(project_id, a.prev, a)
            a.prev = None
        else:
            raise ValueError("keep은 new 또는 prev 여야 합니다.")
        store.save_production(project_id, prod)
    if keep == "prev" and scene_id == anchor_id(project_id):
        _sync_cast_from_anchor(project_id)


def keep_all_new(project_id: str, scene_ids: list[str] | None = None) -> None:
    """고르지 않은 비교를 모두 '새 결과'로 확정한다 (전체 승인 때)."""
    with store.lock(project_id):
        prod = store.get_production(project_id)
        for sid, a in prod.visual.scenes.items():
            if a.prev and (scene_ids is None or sid in scene_ids):
                _delete_unused(project_id, a.prev, a)
                a.prev = None
        store.save_production(project_id, prod)


# ── 장면 하나 만들기 ─────────────────────────────────────────────

def _dialogue(script: Script, scene_id: str) -> str:
    return next((s.dialogue for s in script.scenes if s.id == scene_id), "")


def make_image(project_id: str, scene_id: str, instruction: str = "") -> None:
    script = store.get_script(project_id)
    engine = get_engine()
    _set_busy(project_id, [scene_id], "image")
    try:
        current = store.get_production(project_id).visual.scenes.get(scene_id) or VisualAsset()
        prompt = current.prompt
        if instruction:
            t = timings.Timer()
            prompt = revise_image_prompt(prompt, instruction, _dialogue(script, scene_id))
            timings.record("revise", t.seconds)
        ctx = _context(project_id, script, scene_id)
        ctx.prompt = prompt
        rel = f"visual/{scene_id}_{_ms()}.jpg"
        t = timings.Timer()
        engine.generate_image(ctx, store.project_dir(project_id) / rel)
        timings.record("image", t.seconds, ctx.image_model)
    except Exception as e:  # noqa: BLE001 — 실패해도 기존 이미지는 그대로 둔다
        traceback.print_exc()
        with store.lock(project_id):
            prod = store.get_production(project_id)
            a = prod.visual.scenes.setdefault(scene_id, VisualAsset())
            a.error, a.busy, a.busy_since = explain(e, "이미지 생성"), "", 0
            store.save_production(project_id, prod)
        return
    with store.lock(project_id):
        prod = store.get_production(project_id)
        old = prod.visual.scenes.get(scene_id) or VisualAsset()
        new = VisualAsset(prompt=prompt, motion=old.motion, video_prompt=old.video_prompt, has_person=old.has_person,
                          image=rel, instruction=instruction, v=_ms())
        if old.image:  # 다시 만든 경우: 이전 결과를 남겨 비교하게 한다 (그 전의 비교 대상은 지움)
            _delete_unused(project_id, old.prev, old)
            new.prev = _snapshot(old)
        prod.visual.engine = engine.label
        prod.visual.scenes[scene_id] = new
        store.save_production(project_id, prod)
    if scene_id == anchor_id(project_id, script):
        _sync_cast_from_anchor(project_id)


def make_video(project_id: str, scene_id: str, instruction: str = "") -> None:
    script = store.get_script(project_id)
    asset = store.get_production(project_id).visual.scenes.get(scene_id)
    if not asset or not asset.image:
        raise ValueError(f"{scene_id} 장면 이미지가 없습니다.")
    if not asset.image_approved:
        raise ValueError(f"{scene_id} 장면 이미지를 먼저 승인하세요.")
    engine = get_engine()
    _set_busy(project_id, [scene_id], "video")
    try:
        vprompt = asset.video_prompt
        if instruction:
            t = timings.Timer()
            vprompt = revise_video_prompt(asset.video_prompt or f"Camera: {asset.motion or 'slow push-in'}.", instruction,
                                          _dialogue(script, scene_id))
            timings.record("revise", t.seconds)
        ctx = _context(project_id, script, scene_id)
        ctx.video_prompt = vprompt
        rel = f"visual/{scene_id}_{_ms()}.mp4"
        t = timings.Timer()
        engine.animate(store.project_dir(project_id) / asset.image, ctx, store.project_dir(project_id) / rel)
        timings.record("video", t.seconds, ctx.video_model)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        with store.lock(project_id):
            prod = store.get_production(project_id)
            a = prod.visual.scenes[scene_id]
            a.error, a.busy, a.busy_since = explain(e, "영상 생성"), "", 0
            store.save_production(project_id, prod)
        return
    with store.lock(project_id):
        prod = store.get_production(project_id)
        a = prod.visual.scenes[scene_id]
        if a.video:  # 다시 만든 경우: 이전 영상을 남겨 비교하게 한다
            _delete_unused(project_id, a.prev, a)
            a.prev = _snapshot(a)
        a.video, a.video_prompt, a.error, a.v = rel, vprompt, "", _ms()
        if instruction:
            a.instruction = instruction
        a.busy, a.busy_since = "", 0
        store.save_production(project_id, prod)


# ── 여러 장면 ─────────────────────────────────────────────

def _run_parallel(project_id: str, label: str, fn, scene_ids: list[str], kind: str, model: str, started: float,
                  extra_eta: tuple[float, float] = (0, 0)) -> None:
    """장면별 생성을 PARALLEL개씩 동시에 돌린다. 장면 하나의 실패는 그 장면의 error에 남고 전체는 계속된다."""
    total = len(scene_ids)

    def update(done: int) -> None:
        lo, hi = timings.remaining(kind, total - done, PARALLEL, model)
        _job(project_id, f"{label} ({done}/{total})", started, (lo + extra_eta[0], hi + extra_eta[1]), done, total)

    update(0)
    if not scene_ids:
        return
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        futures = [pool.submit(fn, project_id, sid) for sid in scene_ids]
        for n, fut in enumerate(as_completed(futures), 1):
            fut.result()
            update(n)


def _failed(project_id: str, scene_ids: list[str], what: str) -> int:
    scenes = store.get_production(project_id).visual.scenes
    return sum(1 for sid in scene_ids if not scenes.get(sid) or getattr(scenes[sid], what) is None or scenes[sid].error)


def _finish(project_id: str, label: str, scene_ids: list[str], what: str, started: float) -> None:
    failed = _failed(project_id, scene_ids, what)
    secs = int(time.time() - started)
    msg = f"{label} 완료 ({secs // 60}분 {secs % 60}초)" + (f" · 실패 {failed}개 — 장면에 표시된 원인을 확인하세요" if failed else "")
    store.update_project(project_id, visual_job=JobState(status="done", progress=1, message=msg, started_at=started))


def run_images(project_id: str, scene_ids: list[str] | None = None, instruction: str = "") -> None:
    """scene_ids가 없으면 전체(장면 설계부터 새로), 있으면 그 장면만 다시 만든다(설계 유지, 수정 지시 반영)."""
    script = store.get_script(project_id)
    ids = scene_ids or [s.id for s in script.scenes]
    full = not scene_ids
    started = time.time()
    model = image_model(project_id)
    _set_busy(project_id, ids, "queued")
    try:
        scenes = store.get_production(project_id).visual.scenes
        need_briefs = full or not all(scenes.get(s.id) and scenes[s.id].prompt for s in script.scenes)
        anchor_first = anchor_id(project_id, script) in ids or full
        rest_eta = timings.remaining("image", len(ids) - (1 if anchor_first else 0), PARALLEL, model)
        anchor_eta = timings.remaining("image", 1 if anchor_first else 0, 1, model)
        if need_briefs:
            b = timings.remaining("briefs", 1)
            _job(project_id, "장면 설계 중 — 레퍼런스의 그림체·후킹·구성을 빌려 새 장면을 짜고 있습니다", started,
                 (b[0] + anchor_eta[0] + rest_eta[0], b[1] + anchor_eta[1] + rest_eta[1]))
            t = timings.Timer()
            save_briefs(project_id, only_missing=not full)
            timings.record("briefs", t.seconds)
        anchor = anchor_id(project_id, script)
        if anchor in ids:
            _job(project_id, "기준 장면(첫 장면) 만드는 중 — 나머지 장면이 이 장면의 그림체·인물·분위기를 따릅니다", started,
                 (anchor_eta[0] + rest_eta[0], anchor_eta[1] + rest_eta[1]), 0, len(ids))
            make_image(project_id, anchor, instruction)
        rest = [sid for sid in ids if sid != anchor]
        visual = store.get_production(project_id).visual
        needs_cast = visual.character and not visual.cast_image and any(
            visual.scenes.get(sid) and visual.scenes[sid].has_person for sid in rest)
        if needs_cast:
            p = timings.remaining("portrait", 1, 1, model)
            _job(project_id, "인물 기준 이미지 만드는 중 — 기준 장면의 그림체로 새 인물을 만듭니다", started,
                 (p[0] + rest_eta[0], p[1] + rest_eta[1]))
            make_cast(project_id)
        _run_parallel(project_id, "장면 이미지 생성", lambda pid, sid: make_image(pid, sid, instruction), rest, "image", model,
                      started)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        store.update_project(project_id, visual_job=JobState(status="error", message=explain(e, "장면 설계·인물 준비"), started_at=started))
        return
    finally:
        _set_busy(project_id, ids, "", only_if="queued")
    _finish(project_id, "장면 이미지 생성", ids, "image", started)
    if full:
        prod = store.get_production(project_id)
        ok = sum(1 for sid in ids if prod.visual.scenes.get(sid) and prod.visual.scenes[sid].image)
        gates.open_gate(project_id, "images", f"장면 이미지 {ok}/{len(ids)}장 생성 · 전체 승인하면 영상화를 시작합니다 · 엔진: {prod.visual.engine}")


def run_videos(project_id: str, scene_ids: list[str] | None = None, instruction: str = "") -> None:
    """scene_ids가 없으면 '승인됐지만 아직 영상이 없는 장면'을 영상화한다."""
    from workflow import maybe_open_production_gate  # 순환 import 방지

    ids = scene_ids or approved_without_video(project_id)
    started = time.time()
    _set_busy(project_id, ids, "queued")
    try:
        _run_parallel(project_id, "장면 영상화", lambda pid, sid: make_video(pid, sid, instruction), ids, "video",
                      video_model(project_id), started)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        store.update_project(project_id, visual_job=JobState(status="error", message=explain(e, "장면 영상화"), started_at=started))
        return
    finally:
        _set_busy(project_id, ids, "", only_if="queued")
    _finish(project_id, "장면 영상화", ids, "video", started)
    maybe_open_production_gate(project_id)


def run_cast(project_id: str) -> None:
    started = time.time()
    try:
        _job(project_id, "인물 기준 이미지 다시 만드는 중", started, timings.remaining("portrait", 1, 1, image_model(project_id)))
        make_cast(project_id)
        _finish(project_id, "인물 기준 이미지", [], "image", started)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        store.update_project(project_id, visual_job=JobState(status="error", message=explain(e, "인물 기준 이미지"), started_at=started))


def reset(project_id: str) -> None:
    """비주얼 결과를 모두 지운다 (고른 모델은 유지)."""
    shutil.rmtree(store.project_dir(project_id) / "visual", ignore_errors=True)
    with store.lock(project_id):
        prod = store.get_production(project_id)
        prod.visual = VisualTrack(image_model=prod.visual.image_model, video_model=prod.visual.video_model)
        store.save_production(project_id, prod)
