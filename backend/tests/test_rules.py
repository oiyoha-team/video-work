"""핵심 규칙 테스트. backend 폴더에서: ../.venv/Scripts/python -m tests.test_rules"""
from types import SimpleNamespace

from notify.flow import parse_reply
from planning.analyze import merge_identical_dialogue
from planning.products import parse_markdown_rules
from planning.text import split_sentences
from planning.transcribe import Utterance, _group_words, assign_to_segments, keep_single_owner
from schemas import Segment


def seg(i: int) -> Segment:
    return Segment(index=i, start=i * 2.0, end=i * 2.0 + 2.0, frames=[f"frames/{i:04d}.jpg"])


def test_merge_only_identical():
    # 구간별 문장 번호 목록: 완전히 같을 때만 병합
    keys = [[0], [0], [0, 1], [2], [], [], [2]]
    out, merged_keys = merge_identical_dialogue([seg(i) for i in range(len(keys))], keys)
    assert [s.merged_from for s in out] == [[0, 1], [2], [3], [4], [5], [6]]  # 빈 대사끼리·떨어진 동일 대사는 병합 안 함
    assert merged_keys == [[0], [0, 1], [2], [], [], [2]]
    assert out[0].end == 4.0 and out[0].frames == ["frames/0000.jpg", "frames/0001.jpg"]
    assert [s.index for s in out] == list(range(len(out)))


def test_long_sentence_merges_segments():
    bounds = [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0)]
    utts = [Utterance(0.2, 3.9, "길게 이어지는 한 문장이에요."), Utterance(4.1, 5.5, "다음 문장!")]
    assert assign_to_segments(utts, bounds) == [[0], [0], [1]]


def test_sentence_has_single_owner():
    # 앞 문장이 다음 구간으로 조금 넘어가도 두 번 나오지 않는다
    bounds = [(0.0, 2.0), (2.0, 4.0)]
    utts = [Utterance(0.0, 2.9, "앞 문장이에요."), Utterance(3.0, 3.9, "뒷 문장?")]
    ids = assign_to_segments(utts, bounds)
    assert ids == [[0], [0, 1]]
    assert keep_single_owner(utts, bounds, ids) == [[0], [1]]


def test_sentence_split():
    assert split_sentences("요즘 피부 왜 이래? 화장이 다 들떠. 진짜 좋아!") == ["요즘 피부 왜 이래?", "화장이 다 들떠.", "진짜 좋아!"]
    assert split_sentences("병풀 72.5% 함유. 끝") == ["병풀 72.5% 함유.", "끝"]  # 숫자 소수점은 안 끊음
    assert split_sentences("첫 줄\n둘째 줄") == ["첫 줄", "둘째 줄"]


def test_stt_groups_by_punctuation():
    w = lambda s, e, word: SimpleNamespace(start=s, end=e, word=word)
    words = [w(0.0, 0.3, " 요즘"), w(0.4, 0.8, " 피부"), w(0.9, 1.2, " 왜"), w(1.3, 1.6, " 이래?"),
             w(1.8, 2.0, " 화장이"), w(2.1, 2.5, " 다"), w(2.6, 3.0, " 들떠."), w(4.5, 4.9, " 끝")]
    out = _group_words(words)
    assert [u.text for u in out] == ["요즘 피부 왜 이래?", "화장이 다 들떠.", "끝"]


def test_markdown_template():
    md = """# 제품 정보 입력서

---

## 1. 제품명

무쿠리셋3

---

## 2. 제품 USP

아침 3알 루틴

## 3. 제품 특징

- 1포 3알
- 비용 절약

## 4. 사회적·수치적 근거 및 권위

유산균 17종

## 5. 제품 지칭 키워드

아침 3알 다이어트, 붓기템

## 6. 들어가면 안 되는 표현

없음

## 7. 상세페이지 URL

https://oiyoha.com/shop_view/?idx=5

## 기타 메모

봄 캠페인
"""
    fields, found = parse_markdown_rules(md)
    assert found
    assert fields == {
        "name": "무쿠리셋3",
        "usp": "아침 3알 루틴",
        "features": ["1포 3알", "비용 절약"],
        "evidence": "유산균 17종",
        "keywords": ["아침 3알 다이어트", "붓기템"],
        "forbidden_phrases": [],  # '없음' → 비움
        "detail_url": "https://oiyoha.com/shop_view/?idx=5",
        "extra": "봄 캠페인",
    }


def test_flow_reply_parsing():
    assert parse_reply("진행 A1B2C3") == ("approve", "a1b2c3", "")
    assert parse_reply("수정 a1b2c3 훅을 더 짧게 해줘") == ("revise", "a1b2c3", "훅을 더 짧게 해줘")
    assert parse_reply("안녕하세요") is None
    assert parse_reply("진행") is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("✓", name)
