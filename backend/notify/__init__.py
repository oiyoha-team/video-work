"""승인 알림 채널. 게이트가 열리면 연결된 모든 채널로 알림을 보낸다.

앱 화면(알림 센터)은 /api/gates 폴링으로 항상 동작하고,
여기서는 외부 메신저(Flow 등)로 '밀어 보내는' 채널만 다룬다.
"""
import traceback

from schemas import Gate

from . import flow

CHANNELS = [flow]


def dispatch(gate: Gate) -> list[str]:
    """알림을 보내고 성공한 채널 이름 목록을 반환한다. 알림 실패가 작업을 멈추게 하지는 않는다."""
    sent = []
    for channel in CHANNELS:
        if not channel.is_enabled():
            continue
        try:
            channel.send_gate(gate)
            sent.append(channel.NAME)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    return sent
