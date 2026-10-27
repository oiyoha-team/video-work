"""STT(음성 인식). 엔진은 .env의 STT_ENGINE으로 교체한다.

새 엔진을 추가하려면 transcribe(audio_path) -> list[Utterance]를 구현한 클래스를 만들고
get_engine()에 등록하면 된다.
"""
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

import config

from .text import SENTENCE_END

# 문장은 마침표·물음표·느낌표로 끊는다. 음성 인식이 문장부호를 빠뜨린 경우에만
# 이만큼 긴 쉼을 문장 끝으로 본다.
PAUSE_SPLIT_SEC = 1.0


@dataclass
class Utterance:
    start: float
    end: float
    text: str


class STTEngine(Protocol):
    def transcribe(self, audio_path: Path) -> list[Utterance]: ...


class LocalWhisperEngine:
    """faster-whisper (로컬, 무료). 첫 실행 시 모델을 내려받는다."""

    _model = None
    _model_lock = threading.Lock()

    def _load(self):
        with self._model_lock:
            if LocalWhisperEngine._model is None:
                from faster_whisper import WhisperModel
                LocalWhisperEngine._model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
        return LocalWhisperEngine._model

    def transcribe(self, audio_path: Path) -> list[Utterance]:
        model = self._load()
        segments, _ = model.transcribe(
            _read_wav(audio_path),
            language="ko",
            vad_filter=True,
            word_timestamps=True,
            condition_on_previous_text=False,
        )
        words = [w for seg in segments for w in (seg.words or [])]
        return _group_words(words)


def _read_wav(path: Path) -> np.ndarray:
    """video_ingest가 만든 16kHz mono PCM wav → float32 배열.

    faster-whisper 내부 디코더(PyAV)는 버전 호환 문제가 있어 직접 읽어서 넘긴다.
    """
    with wave.open(str(path), "rb") as wf:
        pcm = wf.readframes(wf.getnframes())
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def _group_words(words) -> list[Utterance]:
    """단어 타임스탬프를 문장 단위(. ? ! 로 끝나는 곳)로 묶는다."""
    utterances: list[Utterance] = []
    buf: list = []

    def flush():
        if buf:
            text = "".join(w.word for w in buf).strip()
            if text:
                utterances.append(Utterance(round(buf[0].start, 2), round(buf[-1].end, 2), text))
            buf.clear()

    for w in words:
        if buf and w.start - buf[-1].end > PAUSE_SPLIT_SEC:
            flush()
        buf.append(w)
        if w.word.strip().endswith(SENTENCE_END):
            flush()
    flush()
    return utterances


class NotImplementedEngine:
    def __init__(self, name: str):
        self.name = name

    def transcribe(self, audio_path: Path) -> list[Utterance]:
        raise NotImplementedError(f"STT 엔진 '{self.name}'은 아직 구현되지 않았습니다. .env의 STT_ENGINE=local로 설정하세요.")


def get_engine() -> STTEngine:
    if config.STT_ENGINE == "local":
        return LocalWhisperEngine()
    return NotImplementedEngine(config.STT_ENGINE)


def _overlap(u: Utterance, bound: tuple[float, float]) -> float:
    return min(u.end, bound[1]) - max(u.start, bound[0])


def assign_to_segments(utterances: list[Utterance], bounds: list[tuple[float, float]]) -> list[list[int]]:
    """문장을 겹치는 2초 구간에 배정한다 (구간별 문장 번호 목록).

    구간 길이의 40% 이상 또는 문장 길이의 50% 이상이 겹치면 그 구간에 넣는다.
    한 문장이 여러 구간에 걸치면 각 구간에 같은 문장이 들어가고,
    이후 '완전히 동일한 대사' 구간만 병합된다 (analyze.merge_identical_dialogue).
    """
    per_segment: list[list[int]] = [[] for _ in bounds]
    for uid, u in enumerate(utterances):
        u_len = max(u.end - u.start, 0.01)
        overlaps = [(i, _overlap(u, b), b[1] - b[0]) for i, b in enumerate(bounds)]
        overlaps = [o for o in overlaps if o[1] > 0]
        if not overlaps:
            continue
        hits = [i for i, ov, seg_len in overlaps if ov >= 0.4 * seg_len or ov >= 0.5 * u_len]
        if not hits:
            hits = [max(overlaps, key=lambda x: x[1])[0]]
        for i in hits:
            per_segment[i].append(uid)
    return per_segment


def keep_single_owner(utterances: list[Utterance], bounds: list[tuple[float, float]], ids: list[list[int]]) -> list[list[int]]:
    """병합 후에도 여러 구간에 남은 문장은 가장 많이 겹치는 구간 한 곳에만 둔다 (문장 중복 방지)."""
    owner: dict[int, int] = {}
    for i, seg_ids in enumerate(ids):
        for uid in seg_ids:
            if uid not in owner or _overlap(utterances[uid], bounds[i]) > _overlap(utterances[uid], bounds[owner[uid]]):
                owner[uid] = i
    return [[uid for uid in seg_ids if owner[uid] == i] for i, seg_ids in enumerate(ids)]
