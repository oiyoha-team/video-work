"""Step 3 우측 Claude 대화 패널.

에이전트는 스크립트를 직접 고치지 않고 '변경 제안'만 돌려준다.
사용자가 [적용]을 눌러야 script.json에 반영된다.
"""
import uuid

from llm import claude_client
from llm.claude_client import strict_object

from . import store
from .text import to_lines
from .script_writer import WRITER_SYSTEM, _context_text, script_json_for_prompt

CHAT_SYSTEM = WRITER_SYSTEM + """

지금은 사용자와 대화하며 이미 작성된 대사 스크립트를 다듬는 단계입니다.
- reply: 사용자에게 할 답변 (한국어, 간결하게, 무엇을 왜 바꿨는지).
- changes: 대사를 고칠 장면만 담는다. dialogue는 그 장면의 '수정 후 전체 대사'다.
- changes[].dialogue는 문장마다 줄바꿈(\\n)으로 구분한다. 한 줄 = 한 문장이며 . ? ! 로 끝낸다.
- 질문이나 의견만 묻는 경우 changes는 빈 배열.
- 장면 추가/삭제/타이밍 변경은 할 수 없다. 요청받으면 reply에서 안내한다."""

MOCK_REPLY = "Claude API 키가 아직 연결되지 않았습니다. 키를 .env에 넣고 서버를 재시작하면 대화로 스크립트를 수정할 수 있습니다. 그 전까지는 왼쪽 편집 영역에서 직접 수정해 주세요."

HISTORY_TURNS = 10  # 최근 몇 개의 메시지만 맥락으로 보낼지


def _schema(scene_ids: list[str]) -> dict:
    change = strict_object({
        "scene_id": {"type": "string", "enum": scene_ids},
        "dialogue": {"type": "string"},
    })
    return strict_object({"reply": {"type": "string"}, "changes": {"type": "array", "items": change}})


def send(project_id: str, text: str) -> list[dict]:
    history = store.get_chat(project_id)
    history.append({"id": uuid.uuid4().hex[:8], "role": "user", "content": text})

    if not claude_client.is_configured():
        history.append({"id": uuid.uuid4().hex[:8], "role": "assistant", "content": MOCK_REPLY, "changes": [], "status": "none"})
        store.save_chat(project_id, history)
        return history

    script = store.get_script(project_id)
    analysis = store.get_analysis(project_id)
    product = store.get_product(project_id)
    if script is None or analysis is None:
        raise ValueError("스크립트가 없습니다.")

    messages = []
    for m in history[:-1][-HISTORY_TURNS:]:
        messages.append({"role": m["role"], "content": m["content"]})
    if messages and messages[0]["role"] != "user":
        messages = messages[1:]
    messages.append({
        "role": "user",
        "content": (
            _context_text(analysis, product)
            + f"\n\n## 현재 스크립트 (JSON)\n{script_json_for_prompt(script)}"
            + f"\n\n## 사용자 요청\n{text}"
        ),
    })

    result = claude_client.json_call(CHAT_SYSTEM, messages, _schema([s.id for s in script.scenes]))
    changes = result.get("changes", [])
    history.append({
        "id": uuid.uuid4().hex[:8],
        "role": "assistant",
        "content": result.get("reply", ""),
        "changes": changes,
        "status": "pending" if changes else "none",
    })
    store.save_chat(project_id, history)
    return history


def resolve(project_id: str, message_id: str, apply: bool) -> list[dict]:
    """제안 적용 또는 무시."""
    history = store.get_chat(project_id)
    msg = next((m for m in history if m["id"] == message_id), None)
    if msg is None or msg.get("status") != "pending":
        raise ValueError("처리할 수 있는 제안이 아닙니다.")

    if apply:
        script = store.get_script(project_id)
        if script.status == "final":
            raise ValueError("확정된 스크립트입니다. 편집을 다시 열어야 적용할 수 있습니다.")
        by_id = {s.id: s for s in script.scenes}
        for c in msg["changes"]:
            scene = by_id.get(c["scene_id"])
            if scene is None:
                continue
            scene.dialogue = to_lines(c["dialogue"])
        store.save_script(project_id, script)

    msg["status"] = "applied" if apply else "dismissed"
    store.save_chat(project_id, history)
    return history
