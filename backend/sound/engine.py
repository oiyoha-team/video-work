"""②-B 사운드(TTS) 엔진. 실제 TTS 서비스를 붙일 때 이 인터페이스를 구현한다.

입력은 자사 제품으로 치환한 스크립트의 '문장'이다 (문장 하나 = 음성 파일 하나).
- TypecastEngine: 타입캐스트 (키가 있으면 기본). 앞뒤 문장을 함께 넘겨 문맥에 맞게 읽는다.
- SystemTTSEngine: 키가 없을 때. OS에 내장된 한국어 음성으로 임시 음성을 만든다.
  - Windows: System.Speech (예: Microsoft Heami)
  - Mac: say 명령 (예: Yuna)
한국어 음성이 없거나 실패하면 SilentEngine(무음)으로 대체한다.
"""
import os
import re
import subprocess
from pathlib import Path
from typing import Protocol

import config
import media
from schemas import TTSSettings, Voice

from . import typecast

_WIN_TTS = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'ko-KR' } | Select-Object -First 1
if (-not $v) { exit 3 }
$s.SelectVoice($v.VoiceInfo.Name)
$s.Rate = [int]$env:TTS_RATE
$s.SetOutputToWaveFile($env:TTS_OUT)
$s.Speak($env:TTS_TEXT)
$s.Dispose()
Write-Output $v.VoiceInfo.Name
"""


class TTSEngine(Protocol):
    name: str
    label: str

    def synthesize(self, text: str, voice: Voice, out: Path, *, previous_text: str = "", next_text: str = "", voice_id: str = "",
                   settings: TTSSettings | None = None) -> str:
        """out(wav)에 음성을 저장하고 사용한 목소리 이름을 반환한다."""
        ...


def _fast(voice: Voice) -> bool:
    return any(k in voice.pace for k in ("빠", "fast"))


class SilentEngine:
    name = "silent"
    label = "mock · 무음 (대사 길이만큼)"

    def synthesize(self, text: str, voice: Voice, out: Path, **_) -> str:
        syllables = len(re.findall(r"[가-힣A-Za-z0-9]", text))
        media.silence(out, max(0.5, syllables / 5))
        return "무음"


class SystemTTSEngine:
    name = "system"
    label = {"windows": "임시 · Windows 기본 음성", "mac": "임시 · Mac 기본 음성"}.get(config.PLATFORM, "임시 · 시스템 음성")

    def synthesize(self, text: str, voice: Voice, out: Path, **_) -> str:
        out.parent.mkdir(parents=True, exist_ok=True)
        if config.PLATFORM == "windows":
            env = {**os.environ, "TTS_TEXT": text, "TTS_OUT": str(out), "TTS_RATE": "2" if _fast(voice) else "0"}
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _WIN_TTS],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
            if r.returncode != 0 or not out.exists():
                raise RuntimeError("Windows 한국어 음성(예: Heami)을 찾을 수 없습니다." if r.returncode == 3 else r.stderr[-300:])
            return r.stdout.strip() or "Windows 음성"
        if config.PLATFORM == "mac":
            listing = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
            m = re.search(r"^(.+?)\s{2,}ko_KR", listing, re.M)
            if not m:
                raise RuntimeError("Mac 한국어 음성(예: Yuna)을 찾을 수 없습니다. 시스템 설정 > 손쉬운 사용 > 읽어주기에서 추가하세요.")
            name = m.group(1).strip()
            aiff = out.with_suffix(".aiff")
            subprocess.run(["say", "-v", name, "-r", "220" if _fast(voice) else "185", "-o", str(aiff), text], check=True)
            media.check(["-y", "-i", str(aiff), "-ac", "1", "-ar", str(media.AUDIO_RATE), "-c:a", "pcm_s16le", str(out)], "음성 변환")
            aiff.unlink(missing_ok=True)
            return name
        raise RuntimeError("이 OS에서는 시스템 음성을 지원하지 않습니다.")


class TypecastEngine:
    name = "typecast"
    label = f"타입캐스트 · {config.TYPECAST_MODEL}"

    def synthesize(self, text: str, voice: Voice, out: Path, *, previous_text: str = "", next_text: str = "", voice_id: str = "",
                   settings: TTSSettings | None = None) -> str:
        s = settings or TTSSettings()
        voice_id = voice_id or pick_voice(voice)["voice_id"]
        # 고른 감정을 이 목소리가 지원하지 않으면 문맥 자동(smart)으로 읽는다
        emotion = s.emotion if s.emotion == "smart" or s.emotion in voice_emotions(voice_id) else "smart"
        typecast.synthesize(voice_id, text, out, previous_text=previous_text, next_text=next_text,
                            tempo=s.tempo, emotion=emotion, emotion_intensity=s.emotion_intensity, pitch=s.pitch)
        return voice_label(voice_id)


# ── 목소리 선택 ─────────────────────────────────────────────

_AGE_HINTS = [("elder", ("60", "70", "노년", "할머니", "할아버지")), ("middle_age", ("40", "50", "중년", "30대 후반")),
              ("teenager", ("10대", "학생", "청소년")), ("young_adult", ("20", "30", "청년"))]
# 실제 목록의 용도 표기 (2026-11 기준). 숏폼 광고에 맞는 순서로 가중치를 준다
_PREFERRED_USE_CASES = {"TikTok/Reels/Shorts": 3, "Ads/Promotion": 3, "Conversational": 1}


def persona_filters(voice: Voice) -> tuple[str | None, str | None]:
    """화자 페르소나 문장('20대 후반 여성, 친근한 실사용자')에서 성별·연령대를 추정한다."""
    text = voice.persona
    gender = "female" if any(k in text for k in ("여성", "여자", "엄마", "언니")) else "male" if any(k in text for k in ("남성", "남자", "아빠", "형")) else None
    age = next((a for a, keys in _AGE_HINTS if any(k in text for k in keys)), None)
    return gender, age


def pick_voice(voice: Voice) -> dict:
    """페르소나에 맞는 타입캐스트 목소리를 고른다 (광고·숏폼·대화체 용도 우선)."""
    voices = typecast.list_voices()
    gender, age = persona_filters(voice)
    for cond in (lambda v: v.get("gender") == gender and v.get("age") == age,
                 lambda v: v.get("gender") == gender,
                 lambda v: True):
        matches = [v for v in voices if cond(v)]
        if matches:
            return max(matches, key=lambda v: sum(_PREFERRED_USE_CASES.get(u, 0) for u in v.get("use_cases") or []))
    raise RuntimeError("타입캐스트 목소리 목록이 비어 있습니다.")


def voice_emotions(voice_id: str) -> list[str]:
    v = next((x for x in typecast.list_voices() if x["voice_id"] == voice_id), None)
    if not v:
        return []
    model = next((m for m in v.get("models", []) if m.get("version") == config.TYPECAST_MODEL), {})
    return model.get("emotions", [])


def voice_label(voice_id: str) -> str:
    v = next((x for x in typecast.list_voices() if x["voice_id"] == voice_id), None)
    return (v["voice_name"].get("kor") or v["voice_name"].get("eng")) if v else voice_id


def get_engine() -> TTSEngine:
    engine = config.SOUND_ENGINE
    if engine == "silent":
        return SilentEngine()
    if engine == "typecast" and typecast.is_configured():
        return TypecastEngine()
    return SystemTTSEngine()
