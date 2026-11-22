"""오류를 사용자가 알아들을 수 있는 '원인 · 해결 방법'으로 바꾼다.

화면에는 첫 줄(무슨 일), 원인, 해결 방법이 보이고 원래 오류 문구는 [원문] 아래에 접혀 있다.
"""
import re

RAW_MARK = "\n[원문] "

# (오류 문구에서 찾을 패턴, 원인, 해결 방법)
_RULES: list[tuple[str, str, str]] = [
    (r"HTTP 401|API 키가 올바르지|invalid.*api.?key|unauthori[sz]ed",
     "API 키가 틀렸거나 만료되었습니다.",
     "프로그램 폴더의 .env 파일에서 해당 서비스 키를 확인하고, 프로그램을 다시 실행하세요."),
    (r"HTTP 402|HTTP 403|크레딧|credit|insufficient|balance|quota",
     "해당 서비스(힉스필드·타입캐스트)의 크레딧이 부족하거나 계정이 비활성 상태입니다.",
     "서비스 사이트에서 크레딧 잔액과 결제 상태를 확인한 뒤 다시 시도하세요."),
    (r"HTTP 429|rate.?limit|too many requests|요청 한도",
     "짧은 시간에 요청이 너무 많아 서비스가 잠시 막았습니다.",
     "1~2분 뒤에 다시 시도하세요. 계속되면 한 번에 만드는 장면 수를 줄이세요."),
    (r"nsfw|부적절한 콘텐츠",
     "생성 AI가 장면 내용을 부적절하다고 판단했습니다 (노출·폭력 등으로 오인).",
     "수정 지시에 '평범한 일상 복장, 건전한 장면'처럼 적어 다시 만들거나, 다른 이미지·영상 모델을 고르세요."),
    (r"15분 안에 끝나지|timed? ?out|timeout",
     "생성 서버가 너무 오래 응답하지 않았습니다 (서비스 혼잡).",
     "잠시 후 다시 시도하세요. 계속되면 다른 모델을 고르세요."),
    (r"연결할 수 없습니다|URLError|getaddrinfo|Connection (refused|reset|aborted)|네트워크",
     "인터넷 연결이 끊겼거나 서비스 서버에 접속하지 못했습니다.",
     "인터넷 연결(회사 방화벽·VPN 포함)을 확인한 뒤 다시 시도하세요."),
    (r"(image|reference).*(too large|too big|dimension|resolution)|file size",
     "참고 이미지(제품 사진 등)가 너무 크거나 형식이 맞지 않습니다.",
     "2단계 제품 사진을 JPG/PNG, 긴 쪽 4000px 이하로 다시 올린 뒤 시도하세요."),
    (r"too many (images|references)|max.*images",
     "참고 이미지가 이 모델의 한도보다 많습니다.",
     "다른 이미지 모델을 고르거나, 2단계에서 제품 사진 수를 줄이세요."),
    (r"모델 .*쓸 수 없습니다|지원하지 않는 .*모델|model.*not (found|available)",
     "고른 모델을 지금 쓸 수 없습니다 (힉스필드에서 내려갔거나 이름이 바뀜).",
     "모델 목록에서 [지금 갱신]을 누른 뒤 다른 모델을 고르세요."),
    (r"ANTHROPIC_API_KEY|Claude가 이 요청|Claude API|Claude 응답",
     "장면 설계를 맡은 Claude 호출이 실패했습니다.",
     "Claude 키(.env의 ANTHROPIC_API_KEY)와 사용 한도를 확인하고 다시 시도하세요."),
    (r"ffmpeg|이미지 비율 맞추기|Invalid data found",
     "받은 이미지·영상 파일을 처리하지 못했습니다 (파일이 깨졌거나 비어 있음).",
     "같은 장면을 다시 만들어 보세요. 계속되면 다른 모델을 고르세요."),
    (r"목소리|voice",
     "선택한 목소리로 음성을 만들지 못했습니다.",
     "다른 목소리를 고르거나 배속을 1.0으로 바꿔 다시 시도하세요."),
    (r"생성에 실패|failed",
     "생성 AI가 이 장면을 만들지 못했습니다 (프롬프트·참고 이미지 조합을 처리하지 못함).",
     "다시 시도하거나, 수정 지시로 장면을 단순하게 바꾸거나, 다른 모델을 고르세요."),
]


def explain(err: BaseException | str, what: str = "") -> str:
    """'무엇이 실패 · 원인 · 해결 방법 · [원문]' 문구."""
    raw = str(err).strip() or err.__class__.__name__
    if RAW_MARK.strip() in raw or raw.startswith("원인:"):
        return raw  # 이미 설명이 붙은 오류
    head = f"{what} 실패" if what else "작업 실패"
    for pattern, cause, fix in _RULES:
        if re.search(pattern, raw, re.I):
            return f"{head}\n원인: {cause}\n해결: {fix}{RAW_MARK}{raw[:500]}"
    return f"{head}\n원인: 예상하지 못한 오류입니다.\n해결: 다시 시도해 보고, 계속되면 아래 원문을 캡처해 전달해 주세요.{RAW_MARK}{raw[:500]}"
