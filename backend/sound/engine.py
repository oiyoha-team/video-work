"""②-B 사운드(TTS) 엔진. 실제 TTS 서비스를 붙일 때 이 인터페이스를 구현한다.

입력은 자사 제품으로 치환한 스크립트의 '문장'이다 (문장 하나 = 음성 파일 하나).
실제 서비스: 일레븐랩스 / 타입캐스트 (ExternalTTSEngine 자리, 연동 예정)
현재 기본값은 SystemTTSEngine: OS에 내장된 한국어 음성으로 임시 음성을 만든다.
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
from schemas import Voice

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

    def synthesize(self, text: str, voice: Voice, out: Path) -> str:
        """out(wav)에 음성을 저장하고 사용한 목소리 이름을 반환한다."""
        ...


def _fast(voice: Voice) -> bool:
    return any(k in voice.pace for k in ("빠", "fast"))


class SilentEngine:
    name = "silent"
    label = "mock · 무음 (대사 길이만큼)"

    def synthesize(self, text: str, voice: Voice, out: Path) -> str:
        syllables = len(re.findall(r"[가-힣A-Za-z0-9]", text))
        media.silence(out, max(0.5, syllables / 5))
        return "무음"


class SystemTTSEngine:
    name = "system"
    label = {"windows": "임시 · Windows 기본 음성", "mac": "임시 · Mac 기본 음성"}.get(config.PLATFORM, "임시 · 시스템 음성")

    def synthesize(self, text: str, voice: Voice, out: Path) -> str:
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


class ExternalTTSEngine:
    """외부 TTS 서비스 연동 자리 (일레븐랩스 / 타입캐스트).

    자사 제품으로 치환한 스크립트의 문장을 하나씩 보내 음성 파일을 받아 온다.
    (레퍼런스 영상의 음성은 대사 추출에만 쓰고 파일로 내보내지 않는다)
    연동 시 synthesize()에서 API를 호출해 out(wav)에 저장하면 된다.
    """

    def __init__(self, name: str, label: str, api_key: str):
        self.name, self.label, self.api_key = name, label, api_key

    def synthesize(self, text: str, voice: Voice, out: Path) -> str:
        raise NotImplementedError(f"{self.label} 연동은 아직 구현되지 않았습니다")


def get_engine() -> TTSEngine:
    engine = config.SOUND_ENGINE
    if engine == "silent":
        return SilentEngine()
    if engine == "elevenlabs":
        return ExternalTTSEngine("elevenlabs", "일레븐랩스", os.getenv("ELEVENLABS_API_KEY", ""))
    if engine == "typecast":
        return ExternalTTSEngine("typecast", "타입캐스트", os.getenv("TYPECAST_API_KEY", ""))
    return SystemTTSEngine()
