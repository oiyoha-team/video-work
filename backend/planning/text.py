"""문장 단위 처리. 대사는 '한 줄 = 한 문장'으로 저장한다.

문장 끝은 마침표·물음표·느낌표로 판단한다. 이 단위가 그대로
자사 제품 문장 치환(1:1)과 TTS 음성 파일(문장당 1개)의 단위가 된다.
"""
import re

SENTENCE_END = (".", "?", "!")
_SPLIT = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """줄바꿈과 문장부호(. ? !) 기준으로 문장 목록을 만든다. '3.5' 같은 숫자는 끊지 않는다."""
    out: list[str] = []
    for line in text.splitlines():
        out += [s.strip() for s in _SPLIT.split(line) if s.strip()]
    return out


def to_lines(text: str) -> str:
    return "\n".join(split_sentences(text))
