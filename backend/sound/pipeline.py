"""②-B 사운드 파이프라인: script.json(확정)의 대사 → 문장별 음성 파일 (비주얼과 병렬 실행).

대사는 '한 줄 = 한 문장'이고, 문장마다 음성 파일을 하나씩 만든다 (sound/s01_1.wav, s01_2.wav …).
마음에 안 드는 문장(또는 장면)만 다시 만들 수 있다. 목소리·배속·감정은 5단계 화면의 설정을 따른다.
"""
import shutil
import time
import traceback

import timings
from errors import explain
from media import wav_duration
from planning import store
from planning.text import split_sentences
from schemas import JobState, SoundAsset, SoundLine, SoundTrack

from .engine import SilentEngine, TypecastEngine, get_engine, pick_voice, voice_label


def _neighbors(script, scene_id: str) -> list[tuple[str, str]]:
    """장면 문장마다 (앞 문장, 뒤 문장). 스크립트 전체 흐름 기준이라 장면 경계를 넘어 이어진다."""
    flat = [(s.id, sentence) for s in script.scenes for sentence in split_sentences(s.dialogue)]
    return [(flat[i - 1][1] if i > 0 else "", flat[i + 1][1] if i + 1 < len(flat) else "")
            for i, (sid, _) in enumerate(flat) if sid == scene_id]


def resolve_voice_id(project_id: str) -> str:
    """선택한 목소리가 없으면 화자 페르소나로 골라 저장한다 (타입캐스트일 때만)."""
    prod = store.get_production(project_id)
    if prod.sound.voice_id or not isinstance(get_engine(), TypecastEngine):
        return prod.sound.voice_id
    chosen = pick_voice(store.get_script(project_id).voice)
    with store.lock(project_id):
        prod = store.get_production(project_id)
        prod.sound.voice_id = chosen["voice_id"]
        prod.sound.voice = voice_label(chosen["voice_id"])
        store.save_production(project_id, prod)
    return chosen["voice_id"]


def _synthesize_line(project_id: str, scene_id: str, n: int, sentence: str, context: tuple[str, str]) -> tuple[SoundLine, str, str]:
    """문장 하나를 만든다. 실패하면 무음으로 대체하고 원인을 남긴다. (SoundLine, 엔진 이름, 목소리 이름)"""
    script = store.get_script(project_id)
    settings = store.get_production(project_id).sound.settings
    voice_id = resolve_voice_id(project_id)
    engine = get_engine()
    rel = f"sound/{scene_id}_{n}.wav"
    out = store.project_dir(project_id) / rel
    line = SoundLine(text=sentence, audio=rel, v=int(time.time() * 1000))
    t = timings.Timer()
    try:
        voice_name = engine.synthesize(sentence, script.voice, out, previous_text=context[0], next_text=context[1],
                                       voice_id=voice_id, settings=settings)
        timings.record("line", t.seconds)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        line.error = explain(e, "음성 생성 (이 문장은 무음으로 대체됨)")
        engine = SilentEngine()
        voice_name = engine.synthesize(sentence, script.voice, out)
    line.duration = round(wav_duration(out), 2)
    return line, engine.label, voice_name


def _save_asset(project_id: str, scene_id: str, asset: SoundAsset, engine_label: str, voice_name: str) -> None:
    asset.duration = round(sum(x.duration for x in asset.lines), 2)
    asset.error = "\n\n".join(f"{i}번 문장: {x.error}" for i, x in enumerate(asset.lines, 1) if x.error)
    asset.v = int(time.time() * 1000)
    asset.busy, asset.busy_since = "", 0
    with store.lock(project_id):
        prod = store.get_production(project_id)
        prod.sound.engine = engine_label
        if voice_name:
            prod.sound.voice = voice_name
        prod.sound.scenes[scene_id] = asset
        store.save_production(project_id, prod)


def _set_busy(project_id: str, scene_ids: list[str], state: str, only_if: str | None = None) -> None:
    with store.lock(project_id):
        prod = store.get_production(project_id)
        for sid in scene_ids:
            a = prod.sound.scenes.get(sid)
            if a is None:
                if not state:
                    continue
                a = prod.sound.scenes[sid] = SoundAsset()
            if only_if is None or a.busy == only_if:
                a.busy, a.busy_since = state, time.time() if state else 0
        store.save_production(project_id, prod)


def clear_busy(project_id: str) -> None:
    """서버가 재시작돼 중단된 작업의 진행 표시를 지운다."""
    with store.lock(project_id):
        prod = store.get_production(project_id)
        if any(a.busy for a in prod.sound.scenes.values()):
            for a in prod.sound.scenes.values():
                a.busy, a.busy_since = "", 0
            store.save_production(project_id, prod)


def make_audio(project_id: str, scene_id: str) -> None:
    """장면의 모든 문장을 다시 만든다."""
    script = store.get_script(project_id)
    scene = next(s for s in script.scenes if s.id == scene_id)
    _set_busy(project_id, [scene_id], "audio")
    for old in (store.project_dir(project_id) / "sound").glob(f"{scene_id}_*.wav"):
        old.unlink()
    context = _neighbors(script, scene_id)
    asset, label, voice_name = SoundAsset(), get_engine().label, ""
    for n, sentence in enumerate(split_sentences(scene.dialogue), 1):
        line, label, voice_name = _synthesize_line(project_id, scene_id, n, sentence, context[n - 1])
        asset.lines.append(line)
    _save_asset(project_id, scene_id, asset, label, voice_name)


def make_line(project_id: str, scene_id: str, n: int) -> None:
    """문장 하나만 다시 만든다."""
    script = store.get_script(project_id)
    scene = next(s for s in script.scenes if s.id == scene_id)
    sentences = split_sentences(scene.dialogue)
    if not 1 <= n <= len(sentences):
        raise ValueError(f"{scene_id} 장면에 {n}번 문장이 없습니다.")
    asset = store.get_production(project_id).sound.scenes.get(scene_id)
    if asset is None or len(asset.lines) != len(sentences):
        make_audio(project_id, scene_id)  # 대사가 바뀌어 문장 수가 다르면 장면 전체를 새로 만든다
        return
    line, label, voice_name = _synthesize_line(project_id, scene_id, n, sentences[n - 1], _neighbors(script, scene_id)[n - 1])
    asset.lines[n - 1] = line
    _save_asset(project_id, scene_id, asset, label, voice_name)


def run_sound(project_id: str, scene_ids: list[str] | None = None) -> None:
    from workflow import maybe_open_production_gate  # 순환 import 방지

    script = store.get_script(project_id)
    ids = scene_ids or [s.id for s in script.scenes]
    counts = {s.id: len(split_sentences(s.dialogue)) for s in script.scenes}
    left = sum(counts.get(sid, 0) for sid in ids)
    started = time.time()
    _set_busy(project_id, ids, "queued")
    try:
        for n, sid in enumerate(ids):
            lo, hi = timings.remaining("line", left)
            store.update_project(project_id, sound_job=JobState(
                status="running", progress=n / len(ids), message=f"음성 생성 ({n + 1}/{len(ids)} 장면)", started_at=started,
                eta_min=lo, eta_max=hi, eta_at=time.time(), done=n, total=len(ids)))
            make_audio(project_id, sid)
            left -= counts.get(sid, 0)
        secs = int(time.time() - started)
        scenes = store.get_production(project_id).sound.scenes
        failed = sum(1 for sid in ids if scenes.get(sid) and scenes[sid].error)
        msg = f"음성 생성 완료 ({secs // 60}분 {secs % 60}초)" + (
            f" · 실패한 문장이 있는 장면 {failed}개 — 문장 아래 원인을 확인하세요" if failed else " · 마음에 안 드는 문장만 다시 만드세요")
        store.update_project(project_id, sound_job=JobState(status="done", progress=1, message=msg, started_at=started))
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        store.update_project(project_id, sound_job=JobState(status="error", message=explain(e, "음성 생성"), started_at=started))
        return
    finally:
        _set_busy(project_id, ids, "", only_if="queued")
        _set_busy(project_id, ids, "", only_if="audio")
    maybe_open_production_gate(project_id)


def reset(project_id: str) -> None:
    """음성 결과를 모두 지운다 (고른 목소리·배속은 유지)."""
    shutil.rmtree(store.project_dir(project_id) / "sound", ignore_errors=True)
    with store.lock(project_id):
        prod = store.get_production(project_id)
        prod.sound = SoundTrack(voice=prod.sound.voice, voice_id=prod.sound.voice_id, settings=prod.sound.settings)
        store.save_production(project_id, prod)
