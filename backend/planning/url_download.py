"""링크(유튜브 · 인스타그램 · 메타 광고 라이브러리 등)에서 레퍼런스 영상을 내려받는다.

yt-dlp를 사용한다. 한 링크에서 영상이 여러 개 나올 수 있으므로(메타 광고는 9:16 · 4:5 등
비율별 버전을 함께 올림) 모두 받은 뒤 후보 목록으로 돌려준다. 고르는 것은 화면에서 한다.

받을 수 없는 링크는 두 단계로 걸러 사용자에게 이유를 알려준다.
  1) check_url: 받기 전에 주소 모양만 보고 알 수 있는 문제 (형식 오류, 채널/계정 주소 등)
  2) explain_error: 받는 중 사이트가 돌려준 오류를 원인별 안내 문구로 바꿈
"""
import re
import shutil
import socket
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import imageio_ffmpeg

import config

from . import video_ingest

MAX_CANDIDATES = 6
PREFERRED_RATIO = "9:16"  # 숏폼 기준으로 세로 영상을 먼저 추천
SUPPORTED = "유튜브 · 인스타그램 · 메타 광고 라이브러리 · 틱톡"
UPDATE_HINT = "계속 안 되면 1_설치하기를 다시 실행해 다운로드 도구를 최신으로 바꿔주세요."


@dataclass
class Candidate:
    id: str
    file: str  # 후보 폴더 기준 파일 이름
    width: int
    height: int
    duration: float
    aspect_ratio: str
    has_audio: bool


class DownloadError(ValueError):
    """화면에 그대로 보여줄 수 있는 쉬운 안내 문구를 담는다."""


def _mmss(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60}분 {sec % 60}초" if sec >= 60 else f"{sec}초"


# ── 1단계: 주소 모양 검사 ─────────────────────────────────────────────

def check_url(raw: str) -> str:
    """주소를 정리해서 돌려준다. 받기 전에 알 수 있는 문제는 DownloadError로 알린다."""
    text = (raw or "").strip()
    if not text:
        raise DownloadError("링크를 입력해주세요.")

    # 설명 문구와 함께 붙여넣은 경우 주소만 골라낸다
    m = re.search(r"https?://\S+", text)
    if m:
        url = m.group(0)
    elif re.match(r"^(www\.)?[\w-]+(\.[\w-]+)+(/\S*)?$", text):
        url = "https://" + text  # 'youtube.com/shorts/…' 처럼 앞부분을 빼고 붙여넣은 경우
    else:
        raise DownloadError("잘못된 URL입니다. 'https://'로 시작하는 영상 주소를 붙여넣어 주세요.")

    u = urlparse(url)
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    if "." not in host:
        raise DownloadError("잘못된 URL입니다. 주소의 사이트 이름 부분이 올바르지 않습니다.")
    path = u.path.rstrip("/")
    query = parse_qs(u.query)

    if host in ("youtube.com", "music.youtube.com"):
        if path == "/watch":
            vid = (query.get("v") or [""])[0]
            if not vid:
                raise DownloadError("잘못된 유튜브 주소입니다. 영상 번호(v=…)가 빠져 있습니다. 영상 페이지의 주소를 다시 복사해 주세요.")
            if not re.fullmatch(r"[\w-]{11}", vid):
                raise DownloadError("잘못된 유튜브 주소입니다. 영상 번호(v=…)가 잘렸거나 틀렸습니다. 주소를 다시 복사해 주세요.")
        elif re.match(r"^/(@|channel/|c/|user/)", path):
            raise DownloadError("유튜브 채널 주소입니다. 채널 안의 영상 하나를 열어 그 주소를 넣어주세요.")
        elif path in ("/playlist", "/results", "/feed", ""):
            raise DownloadError("유튜브 재생목록·검색·홈 주소입니다. 영상 하나를 열어 그 주소를 넣어주세요.")
    elif host == "instagram.com":
        if path.startswith("/stories"):
            raise DownloadError("인스타그램 스토리는 로그인해야 볼 수 있어 가져올 수 없습니다. 릴스나 게시물 주소를 넣어주세요.")
        if not re.match(r"^(/[\w.]+)?/(reel|reels|p|tv)/[\w-]+", path):
            raise DownloadError("인스타그램 계정(프로필) 주소입니다. 릴스나 게시물 하나를 열어 그 주소를 넣어주세요.")
    elif host == "facebook.com" and path.startswith("/ads/library"):
        ad_id = (query.get("id") or [""])[0]
        if not ad_id:
            raise DownloadError("메타 광고 라이브러리의 검색 페이지 주소입니다. 광고 하나의 링크(주소에 ?id=숫자 가 있는 것)를 넣어주세요.")
        if not ad_id.isdigit():
            raise DownloadError("잘못된 광고 라이브러리 주소입니다. 광고 번호(id=…)는 숫자여야 합니다.")
    elif host == "tiktok.com":
        if re.fullmatch(r"/@[\w.]+", path):
            raise DownloadError("틱톡 계정(프로필) 주소입니다. 영상 하나를 열어 그 주소를 넣어주세요.")
    return url


# ── 2단계: 받는 중 생긴 오류를 원인별 안내로 ─────────────────────────────

def _internet_ok() -> bool:
    try:
        socket.getaddrinfo("www.google.com", 443)
        return True
    except OSError:
        return False


def explain_error(msg: str) -> str:
    low = msg.lower()
    has = lambda *keys: any(k in low for k in keys)  # noqa: E731

    # 연결 문제
    if has("getaddrinfo failed", "name or service not known", "nodename nor servname", "no address associated"):
        if not _internet_ok():
            return "인터넷에 연결되어 있지 않습니다. 인터넷 연결을 확인한 뒤 다시 시도하세요."
        return "존재하지 않는 사이트 주소입니다. 주소에 오타가 없는지 확인해 주세요."
    if has("certificate_verify_failed", "ssl:"):
        return "보안 연결(인증서) 문제로 사이트에 접속할 수 없습니다. 회사 네트워크나 백신 프로그램이 막고 있을 수 있습니다."
    if has("timed out", "timeout", "connection reset", "connection refused", "connection aborted", "remote end closed"):
        return "사이트가 응답하지 않습니다. 잠시 후 다시 시도하세요."
    if has("http error 429", "too many requests", "rate-limit", "rate limit"):
        return "짧은 시간에 요청이 많아 사이트가 잠시 막았습니다. 몇 분 뒤 다시 시도하세요."

    # 지원하지 않는 주소
    if has("unsupported url"):
        return f"지원하지 않는 사이트의 주소입니다. {SUPPORTED} 링크를 넣어주세요."

    # 영상 상태 (유튜브 등)
    if has("not a bot", "confirm you’re not", "confirm you're not"):
        return f"유튜브가 자동 접근으로 판단해 막았습니다. 잠시 후 다시 시도하거나, 영상을 직접 받아서 올려주세요. {UPDATE_HINT}"
    if has("confirm your age", "age-restricted", "age restricted", "inappropriate for some users"):
        return "연령 제한 영상이라 로그인 없이 가져올 수 없습니다. 영상을 직접 받아서 올려주세요."
    if has("private video", "video is private", "this account is private"):
        return "비공개 영상이라 가져올 수 없습니다."
    if has("members-only", "members only", "join this channel"):
        return "채널 멤버십 전용 영상이라 가져올 수 없습니다."
    if has("not available in your country", "geo restrict", "geo-restrict", "blocked it in your country"):
        return "이 나라(한국)에서는 볼 수 없도록 막힌 영상입니다."
    if has("live event will begin", "premieres in", "premiere will begin"):
        return "아직 시작하지 않은 라이브·최초 공개 영상입니다. 공개된 뒤에 다시 시도하세요."
    if has("is live", "live stream", "livestream"):
        return "진행 중인 라이브 방송은 가져올 수 없습니다. 방송이 끝난 뒤 다시 시도하세요."
    if has("video unavailable", "video is unavailable", "has been removed", "no longer available", "does not exist",
           "http error 404", "404: not found", "not found"):
        return "존재하지 않거나 삭제된 영상입니다. 주소가 맞는지 확인해 주세요."

    # 사이트별
    if "[instagram" in low and has("empty media response"):
        return "인스타그램 게시물을 열 수 없습니다. 삭제된 게시물이거나, 비공개 계정이거나, 로그인해야 볼 수 있는 게시물입니다. 주소도 다시 확인해 주세요."
    if "[facebook:ads]" in low:
        return "광고를 찾을 수 없습니다. 광고 번호가 틀렸거나, 게재가 끝나 내려간 광고일 수 있습니다."
    if "[tiktok" in low:
        return "틱톡 영상을 열 수 없습니다. 삭제됐거나 비공개 영상이거나, 주소가 틀렸을 수 있습니다."
    if has("login", "log in", "logged-in", "cookies", "sign in"):
        return "로그인해야 볼 수 있는 영상이라 가져올 수 없습니다. 영상을 직접 받아서 올려주세요."
    if has("no video formats", "no video", "there's no video", "requested format is not available"):
        return "이 링크에는 영상이 없습니다. 사진·이미지 게시물(광고)일 수 있습니다."
    if has("http error 403", "forbidden"):
        return "사이트가 접근을 막았습니다 (접근 권한 없음). 공개된 영상인지 확인해 주세요."
    if "[generic]" in low:
        return f"영상을 찾을 수 없는 페이지입니다. {SUPPORTED}의 영상 하나의 주소를 넣어주세요."
    if has("unable to extract", "unexpected response"):
        return f"사이트 화면 구조가 바뀌어 영상을 읽지 못했습니다. {UPDATE_HINT}"
    return f"영상을 받지 못했습니다 ({msg.replace('ERROR: ', '').strip()[:160]}). {UPDATE_HINT}"


# ── 다운로드 ─────────────────────────────────────────────

def _ffmpeg_dir() -> Path:
    """yt-dlp는 'ffmpeg(.exe)'라는 이름의 실행 파일만 찾으므로, imageio-ffmpeg 것을 복사해 둔다."""
    src = Path(imageio_ffmpeg.get_ffmpeg_exe())
    tools = config.DATA_DIR / ".tools"
    dest = tools / ("ffmpeg.exe" if config.PLATFORM == "windows" else "ffmpeg")
    if not dest.exists() or dest.stat().st_size != src.stat().st_size:
        tools.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    return tools


def download_candidates(raw_url: str, out_dir: Path) -> list[Candidate]:
    import yt_dlp  # 무거우므로 필요할 때만 불러온다

    url = check_url(raw_url)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    limit = config.MAX_VIDEO_SEC
    skipped: list[str] = []  # 받지 않고 건너뛴 이유

    def _filter(info: dict, *, incomplete: bool = False) -> str | None:
        """받기 전에 길이·라이브 여부를 보고 건너뛸 영상을 고른다."""
        if info.get("live_status") in ("is_live", "is_upcoming"):
            skipped.append("live")
            return "라이브"
        dur = info.get("duration")
        if dur and dur > limit + 5:
            skipped.append(f"long:{dur}")
            return "너무 김"
        return None

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,  # 유튜브 재생목록 링크면 그 영상 하나만
        "playlist_items": f"1:{MAX_CANDIDATES}",
        "format": "bv*[height<=1920]+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "ffmpeg_location": str(_ffmpeg_dir()),
        "match_filter": _filter,
        # 유튜브 보안 확인을 풀 때 설치된 Node.js를 사용
        "js_runtimes": {"node": {}, "deno": {}},
        "remote_components": ["ejs:github"],
        "socket_timeout": 30,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise DownloadError(explain_error(str(e))) from e

    candidates: list[Candidate] = []
    for f in sorted(out_dir.iterdir()):
        if not f.is_file() or f.suffix.lower() not in (".mp4", ".webm", ".mkv", ".mov", ".m4v"):
            continue
        try:
            info = video_ingest.probe(f)
        except ValueError:
            continue  # 소리만 있는 파일 등
        candidates.append(Candidate(
            id=f.stem,
            file=f.name,
            width=info.width,
            height=info.height,
            duration=round(info.duration, 2),
            aspect_ratio=video_ingest.closest_aspect_ratio(info.width, info.height),
            has_audio=info.has_audio,
        ))

    if not candidates:
        shutil.rmtree(out_dir, ignore_errors=True)
        longs = [float(s.split(":")[1]) for s in skipped if s.startswith("long:")]
        if longs:
            raise DownloadError(
                f"영상 길이가 {_mmss(min(longs))}입니다. {limit // 60}분 이하 영상만 사용할 수 있습니다. "
                "필요한 부분만 잘라서 직접 올려주세요."
            )
        if "live" in skipped:
            raise DownloadError("진행 중이거나 시작 전인 라이브 방송은 가져올 수 없습니다.")
        raise DownloadError("이 링크에는 영상이 없습니다. 사진·이미지 게시물(광고)이거나, 영상이 아닌 페이지일 수 있습니다.")

    # 추천(세로 9:16)을 맨 앞으로
    candidates.sort(key=lambda c: (c.aspect_ratio != PREFERRED_RATIO, -c.height))
    return candidates


def as_dicts(candidates: list[Candidate]) -> list[dict]:
    return [asdict(c) for c in candidates]
