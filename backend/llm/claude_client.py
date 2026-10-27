"""Claude API 래퍼.

ANTHROPIC_API_KEY가 비어 있으면 is_configured()가 False를 반환하고,
각 기능은 mock 결과로 대체한다 (UI 흐름 테스트용).
"""
import base64
import json
from pathlib import Path

import anthropic

import config

_client: anthropic.Anthropic | None = None


class ClaudeNotConfigured(RuntimeError):
    pass


class ClaudeError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def _get_client() -> anthropic.Anthropic:
    global _client
    if not is_configured():
        raise ClaudeNotConfigured("ANTHROPIC_API_KEY가 설정되지 않았습니다. .env 파일에 키를 넣고 서버를 재시작하세요.")
    if _client is None:
        headers = {"anthropic-workspace-id": config.ANTHROPIC_WORKSPACE_ID} if config.ANTHROPIC_WORKSPACE_ID else None
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, default_headers=headers)
    return _client


def image_block(path: Path) -> dict:
    media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}


def strict_object(properties: dict) -> dict:
    """structured output용: 모든 필드 required + additionalProperties false."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties.keys()),
        "additionalProperties": False,
    }


def json_call(
    system: str,
    messages: list[dict],
    schema: dict,
    *,
    max_tokens: int = 32000,
    effort: str = "medium",
) -> dict:
    """JSON 스키마에 맞는 응답을 받아 dict로 반환한다."""
    client = _get_client()
    try:
        # 거절(refusal) 시 서버가 자동으로 대체 모델로 재시도하도록 fallbacks 사용
        with client.beta.messages.stream(
            model=config.CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise ClaudeError("API 키가 올바르지 않습니다.") from e
    except anthropic.RateLimitError as e:
        raise ClaudeError("요청 한도를 초과했습니다. 잠시 후 다시 시도하세요.") from e
    except anthropic.BadRequestError as e:
        if "anthropic-workspace-id" in str(e.message):
            raise ClaudeError(
                "이 API 키는 워크스페이스 ID가 필요합니다. .env의 ANTHROPIC_WORKSPACE_ID에 워크스페이스 ID(wrkspc_…)를 넣거나, "
                "워크스페이스용 API 키(sk-ant-api03-…)로 바꾼 뒤 프로그램을 다시 실행하세요."
            ) from e
        raise ClaudeError(f"Claude API 오류 (400): {e.message}") from e
    except anthropic.APIStatusError as e:
        raise ClaudeError(f"Claude API 오류 ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise ClaudeError("Claude API에 연결할 수 없습니다. 네트워크를 확인하세요.") from e

    if message.stop_reason == "refusal":
        raise ClaudeError("Claude가 이 요청에 대한 응답을 거절했습니다. 입력 내용을 확인하세요.")
    if message.stop_reason == "max_tokens":
        raise ClaudeError("응답이 너무 길어 중간에 잘렸습니다. 영상 길이를 줄이거나 다시 시도하세요.")

    text = next((b.text for b in message.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ClaudeError("Claude 응답을 해석하지 못했습니다.") from e
