"""②-B 사운드 파이프라인: script.json(확정)의 대사 → 문장별 음성 파일 (비주얼과 병렬 실행).

대사는 '한 줄 = 한 문장'이고, 문장마다 음성 파일을 하나씩 만든다 (sound/s01_1.wav, s01_2.wav …).
"""
import time
import traceback

from media import wav_duration
from planning import store
from planning.text import split_sentences
from schemas import JobState, SoundAsset, SoundLine

from .engine import SilentEngine, get_engine


def make_audio(project_id: str, scene_id: str) -> None:
    script = store.get_script(project_id)
    scene = next(s for s in script.scenes if s.id == scene_id)
    sound_dir = store.project_dir(project_id) / "sound"
    for old in sound_dir.glob(f"{scene_id}_*.wav"):
        old.unlink()

    asset = SoundAsset(v=int(time.time() * 1000))
    engine = get_engine()
    voice_name = ""
    errors: list[str] = []
    for n, sentence in enumerate(split_sentences(scene.dialogue), 1):
        rel = f"sound/{scene_id}_{n}.wav"
        out = store.project_dir(project_id) / rel
        try:
            voice_name = engine.synthesize(sentence, script.voice, out)
        except Exception as e:  # noqa: BLE001 — 시스템 음성이 없으면 무음으로 대체
            errors.append(f"{n}번 문장: {e} → 무음으로 대체")
            engine = SilentEngine()
            voice_name = engine.synthesize(sentence, script.voice, out)
        asset.lines.append(SoundLine(text=sentence, audio=rel, duration=round(wav_duration(out), 2)))
    asset.duration = round(sum(line.duration for line in asset.lines), 2)
    asset.error = "\n".join(errors)

    with store.lock(project_id):
        prod = store.get_production(project_id)
        prod.sound.engine = engine.label
        if voice_name:
            prod.sound.voice = voice_name
        prod.sound.scenes[scene_id] = asset
        store.save_production(project_id, prod)


def run_sound(project_id: str) -> None:
    from workflow import maybe_open_production_gate  # 순환 import 방지

    script = store.get_script(project_id)
    ids = [s.id for s in script.scenes]
    try:
        for n, sid in enumerate(ids):
            store.update_project(project_id, sound_job=JobState(status="running", progress=n / len(ids), message=f"음성 생성 ({n + 1}/{len(ids)} 장면)"))
            make_audio(project_id, sid)
        store.update_project(project_id, sound_job=JobState(status="done", progress=1, message="음성 생성 완료"))
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        store.update_project(project_id, sound_job=JobState(status="error", message=str(e)))
        return
    maybe_open_production_gate(project_id)
