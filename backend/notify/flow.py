"""Flow(flow.team) 메신저 알림 채널 — 연동 자리만 잡아둔 상태.

[보내기] 게이트가 열리면 build_message()로 만든 메시지를 Flow 채팅방(봇)으로 보낸다.
         → Flow API 문서를 받으면 send_gate()의 전송 부분만 구현하면 된다.

[받기]   사람이 Flow에서 [진행]/[수정]을 누르거나 "진행 a1b2c3" 처럼 답장하면
         그 결과를 POST /api/flow/webhook 으로 전달받아 게이트를 처리한다 (main.py에 구현됨).
         방식은 Flow 기능에 따라 둘 중 하나:
           A) Flow가 버튼 클릭을 웹훅으로 보내주는 경우 → 외부에서 이 PC에 접속할 주소가 필요
              (PUBLIC_BASE_URL에 터널 주소 설정, 예: Cloudflare Tunnel)
           B) 웹훅이 없는 경우 → 이 서버가 Flow 채팅방 답장을 주기적으로 읽어(polling) 처리
              (외부 접속 주소 불필요)
"""
import config
from schemas import GATE_STEP, Gate

NAME = "flow"


def is_enabled() -> bool:
    return bool(config.FLOW_API_TOKEN and config.FLOW_ROOM_ID)


def build_message(gate: Gate) -> str:
    link = f"{config.PUBLIC_BASE_URL}/#p={gate.project_id}&s={GATE_STEP[gate.kind]}"
    return "\n".join([
        f"[오이요하 영상 자동화] {gate.project_name}",
        f"■ {gate.title}",
        gate.summary,
        "",
        f"▶ 다음 단계로 진행: 「진행 {gate.id}」",
        f"✎ 수정 요청: 「수정 {gate.id} 수정할 내용」",
        f"화면에서 확인: {link}",
    ])


def send_gate(gate: Gate) -> None:
    message = build_message(gate)
    # TODO(Flow 연동): Flow API로 FLOW_ROOM_ID 채팅방에 message 전송 (버튼 지원 시 진행/수정 버튼 포함)
    raise NotImplementedError(f"Flow 전송이 아직 구현되지 않았습니다.\n{message}")


def parse_reply(text: str) -> tuple[str, str, str] | None:
    """채팅 답장 "진행 a1b2c3" / "수정 a1b2c3 훅을 더 짧게" → (action, gate_id, comment)."""
    parts = text.strip().split(maxsplit=2)
    if len(parts) < 2:
        return None
    verb, gate_id = parts[0], parts[1].lower()
    comment = parts[2] if len(parts) > 2 else ""
    if verb in ("진행", "승인", "ok", "OK"):
        return "approve", gate_id, comment
    if verb in ("수정", "반려"):
        return "revise", gate_id, comment
    return None
