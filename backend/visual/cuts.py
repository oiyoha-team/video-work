"""컷 계획: 장면(대사 단위) 하나를 이미지 여러 장(컷)으로 나눈다.

- 레퍼런스 분석에 컷(화면 전환 기준, 최대 2초)이 있으면 그대로 따른다.
  레퍼런스 6초 구간에 컷이 3개면 우리 장면도 컷 3개 → 6초 동안 같은 이미지가 나오지 않는다.
- 예전 분석(컷 정보 없음)이나 직접 추가한 장면은 길이로 나눈다 (한 컷 최대 MAX_CUT_SEC).
- 컷 시간은 장면 시작 기준(초)이다. 컷을 추가하면 옆 컷 시간을 반으로 나누고, 지우면 옆 컷에 붙인다.
- 한 샷이 다음 장면(다음 문장)까지 이어지면 다음 장면 첫 컷을 link_prev로 표시한다.
  그 컷은 이미지·영상을 따로 만들지 않고 앞 컷('대표 컷')의 것을 이어 쓴다 → 같은 장면 중복 생성 방지.
- 예전 프로젝트(장면당 1컷)는 cut_id = scene_id 로 그대로 쓴다.
"""
import math
import time

from config import MAX_CUT_SEC
from planning import store
from schemas import Production, Script, VisualAsset

from .briefs import reference_for

PLAN_VERSION = 1


def _ms() -> int:
    return int(time.time() * 1000)


def _scene_len(scene) -> float:
    return max(scene.end - scene.start, 0.1)


def _fresh_cuts(project_id: str, scene, prev_scene=None) -> list[VisualAsset]:
    """레퍼런스 컷을 우리 장면 길이에 맞춰 옮긴다 (장면 시작 기준 초).

    앞 장면이 바로 앞 레퍼런스 구간과 짝일 때만 '앞 장면에서 이어지는 샷'(cont)을 이어 쓰기로 표시한다.
    """
    length = _scene_len(scene)
    ref = reference_for(project_id, scene.ref_segment)
    ref_cuts = (ref or {}).get("cuts") or []
    if ref and ref_cuts:
        ref_len = max(ref["end"] - ref["start"], 0.1)
        scale = length / ref_len
        can_link = (prev_scene is not None and prev_scene.ref_segment is not None and scene.ref_segment is not None
                    and prev_scene.ref_segment == scene.ref_segment - 1)
        return [VisualAsset(scene_id=scene.id, start=round((c["start"] - ref["start"]) * scale, 2),
                            end=round((c["end"] - ref["start"]) * scale, 2), ref_frame=c.get("frame") or None,
                            ref_desc=c.get("description", ""), split=c.get("split", False),
                            link_prev=bool(k == 0 and can_link and c.get("cont")))
                for k, c in enumerate(ref_cuts)]
    # 컷 정보가 없으면(예전 분석·직접 넣은 장면) 한 컷. MAX_CUT_SEC를 쓰면 그 길이로 나눈다
    n = max(1, math.ceil(length / MAX_CUT_SEC - 1e-6)) if MAX_CUT_SEC else 1
    frames = (ref or {}).get("frames") or []
    out = []
    for k in range(n):
        a, b = length * k / n, length * (k + 1) / n
        frame = frames[min(len(frames) - 1, int(k * len(frames) / n))] if frames else None
        out.append(VisualAsset(scene_id=scene.id, start=round(a, 2), end=round(b, 2), ref_frame=frame,
                               ref_desc=(ref or {}).get("scene", ""), split=k > 0))
    return out


def scene_cut_ids(prod: Production, scene_id: str) -> list[str]:
    return prod.visual.scene_cuts.get(scene_id) or [scene_id]


def ordered(project_id: str, script: Script | None = None, prod: Production | None = None) -> list[str]:
    """영상 순서대로 모든 컷 id."""
    script = script or store.get_script(project_id)
    prod = prod or store.get_production(project_id)
    return [cid for s in script.scenes for cid in scene_cut_ids(prod, s.id)]


def _linked(prod: Production, cid: str) -> bool:
    c = prod.visual.scenes.get(cid)
    return bool(c and c.link_prev)


def owners(project_id: str, script: Script | None = None, prod: Production | None = None) -> list[str]:
    """이미지·영상을 실제로 만드는 컷 (이어 쓰는 컷 제외). 첫 컷은 항상 대표 컷."""
    prod = prod or store.get_production(project_id)
    order = ordered(project_id, script, prod)
    return [cid for i, cid in enumerate(order) if i == 0 or not _linked(prod, cid)]


def owner_of(project_id: str, cid: str, script: Script | None = None, prod: Production | None = None) -> str:
    """이어 쓰는 컷이면 이미지·영상을 가진 대표 컷, 아니면 자기 자신."""
    prod = prod or store.get_production(project_id)
    order = ordered(project_id, script, prod)
    i = order.index(cid) if cid in order else -1
    while i > 0 and _linked(prod, order[i]):
        i -= 1
    return order[i] if i >= 0 else cid


def chain(project_id: str, owner: str, script: Script | None = None, prod: Production | None = None) -> list[str]:
    """대표 컷과 그 컷을 이어 쓰는 뒤 컷들 (한 샷)."""
    prod = prod or store.get_production(project_id)
    order = ordered(project_id, script, prod)
    if owner not in order:
        return [owner]
    i = order.index(owner)
    out = [owner]
    while i + 1 < len(order) and _linked(prod, order[i + 1]):
        i += 1
        out.append(order[i])
    return out


def cut_len(prod: Production, cid: str) -> float:
    c = prod.visual.scenes.get(cid)
    return max((c.end - c.start) if c else 0, 0.1)


def shot_len(project_id: str, owner: str, script: Script | None = None, prod: Production | None = None) -> float:
    """대표 컷이 만드는 영상 길이 = 이어 쓰는 컷까지 합친 길이."""
    prod = prod or store.get_production(project_id)
    return sum(cut_len(prod, c) for c in chain(project_id, owner, script, prod))


def unlink(project_id: str, cut_id: str) -> None:
    """이어 쓰던 컷을 따로 만드는 컷으로 바꾼다."""
    with store.lock(project_id):
        prod = store.get_production(project_id)
        c = prod.visual.scenes.get(cut_id)
        if c is None:
            raise ValueError("컷을 찾을 수 없습니다.")
        c.link_prev = False
        store.save_production(project_id, prod)


def _unlink_after(project_id: str, prod: Production, cid: str) -> None:
    """cid 바로 뒤 컷이 cid를 이어 쓰고 있었다면 끊는다 (컷을 넣거나 지워 앞 컷이 바뀐 경우)."""
    order = ordered(project_id, None, prod)
    if cid in order:
        i = order.index(cid)
        if i + 1 < len(order) and _linked(prod, order[i + 1]):
            prod.visual.scenes[order[i + 1]].link_prev = False


def ensure(project_id: str, rebuild: bool = False) -> None:
    """컷 계획이 없는 장면에 컷을 만든다. rebuild면 예전 방식(장면당 1컷) 계획을 레퍼런스 컷 기준으로 새로 짠다.

    이미 이미지가 있는 예전 장면은 rebuild가 아니면 그대로 둔다 (만든 이미지를 지키기 위해).
    """
    script = store.get_script(project_id)
    pdir = store.project_dir(project_id)
    with store.lock(project_id):
        prod = store.get_production(project_id)
        before = prod.model_dump_json()
        v = prod.visual
        if rebuild and v.cut_plan_version < PLAN_VERSION:
            for asset in v.scenes.values():
                for rel in (asset.image, asset.video):
                    if rel:
                        (pdir / rel).unlink(missing_ok=True)
            v.scenes, v.scene_cuts, v.cast_image = {}, {}, None
        prev_scene = None
        for s in script.scenes:
            this_prev, prev_scene = prev_scene, s
            if s.id in v.scene_cuts:
                # 기획안에서 장면 길이가 바뀌었으면 컷 시간도 같은 비율로 맞춘다
                cs = [v.scenes[c] for c in v.scene_cuts[s.id] if c in v.scenes]
                old_len = cs[-1].end if cs else 0
                if cs and old_len > 0 and abs(old_len - _scene_len(s)) > 0.05:
                    scale = _scene_len(s) / old_len
                    for c in cs:
                        c.start, c.end = round(c.start * scale, 2), round(c.end * scale, 2)
                continue
            legacy = v.scenes.get(s.id)
            if legacy and (legacy.image or legacy.video) and not rebuild:
                legacy.scene_id, legacy.start, legacy.end = s.id, 0, round(_scene_len(s), 2)
                v.scene_cuts[s.id] = [s.id]
                continue
            v.scenes.pop(s.id, None)
            ids = []
            for k, cut in enumerate(_fresh_cuts(project_id, s, this_prev), 1):
                cid = f"{s.id}c{k}"
                v.scenes[cid] = cut
                ids.append(cid)
            v.scene_cuts[s.id] = ids
        # 기획안에서 지운 장면의 컷 계획은 정리한다
        alive = {s.id for s in script.scenes}
        for sid in [k for k in v.scene_cuts if k not in alive]:
            for cid in v.scene_cuts.pop(sid):
                v.scenes.pop(cid, None)
        if all(len(ids) and (ids != [sid]) for sid, ids in v.scene_cuts.items()) or rebuild:
            v.cut_plan_version = PLAN_VERSION
        if prod.model_dump_json() != before:  # 화면이 자주 부르므로 바뀐 게 있을 때만 저장
            store.save_production(project_id, prod)


def add(project_id: str, scene_id: str, after: str | None, note: str = "") -> str:
    """장면 안에 컷을 추가한다. after 컷(없으면 첫 컷)의 시간을 반으로 나눠 새 컷에 준다."""
    ensure(project_id)
    with store.lock(project_id):
        prod = store.get_production(project_id)
        ids = list(scene_cut_ids(prod, scene_id))
        if scene_id not in prod.visual.scene_cuts:
            raise ValueError("장면을 찾을 수 없습니다.")
        base_id = after if after in ids else ids[0]
        base = prod.visual.scenes[base_id]
        mid = round((base.start + base.end) / 2, 2)
        cid = f"{scene_id}x{_ms()}"
        new = VisualAsset(scene_id=scene_id, note=note.strip(), added=True, ref_frame=base.ref_frame,
                          ref_desc=base.ref_desc, has_person=base.has_person)
        if after in ids:  # base 뒤에: base = 앞 절반, 새 컷 = 뒤 절반
            new.start, new.end, base.end = mid, base.end, mid
            ids.insert(ids.index(base_id) + 1, cid)
        else:  # 맨 앞에
            new.start, new.end, base.start = base.start, mid, mid
            ids.insert(0, cid)
        prod.visual.scenes[cid] = new
        prod.visual.scene_cuts[scene_id] = ids
        # 새 컷이 끼어들면 그 뒤에서 앞 컷을 이어 쓰던 컷은 끊는다 (이제 앞 컷이 새 컷)
        _unlink_after(project_id, prod, cid)
        store.save_production(project_id, prod)
    return cid


def delete(project_id: str, cut_id: str) -> None:
    """컷을 지운다. 그 시간은 앞 컷(첫 컷이면 뒤 컷)에 붙인다. 장면의 마지막 한 컷은 지울 수 없다."""
    pdir = store.project_dir(project_id)
    with store.lock(project_id):
        prod = store.get_production(project_id)
        cut = prod.visual.scenes.get(cut_id)
        if cut is None:
            raise ValueError("컷을 찾을 수 없습니다.")
        if cut.busy:
            raise ValueError("이 컷을 만드는 중입니다. 끝난 뒤 지우세요.")
        sid = cut.scene_id or cut_id
        ids = list(scene_cut_ids(prod, sid))
        if len(ids) <= 1:
            raise ValueError("장면에는 컷이 하나 이상 있어야 합니다. 장면 자체를 빼려면 기획안(3단계)에서 장면을 삭제하세요.")
        _unlink_after(project_id, prod, cut_id)  # 지우는 컷을 이어 쓰던 뒤 컷은 따로 만든다
        i = ids.index(cut_id)
        if i > 0:
            prod.visual.scenes[ids[i - 1]].end = cut.end
        else:
            prod.visual.scenes[ids[1]].start = cut.start
        ids.pop(i)
        for rel in (cut.image, cut.video, cut.prev.image if cut.prev else None, cut.prev.video if cut.prev else None):
            if rel:
                (pdir / rel).unlink(missing_ok=True)
        prod.visual.scenes.pop(cut_id, None)
        prod.visual.scene_cuts[sid] = ids
        store.save_production(project_id, prod)
