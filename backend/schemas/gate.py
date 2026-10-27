"""승인 게이트: 자동 단계가 끝나면 사람에게 [진행] / [수정]을 묻는다.

앱 화면과 Flow 메신저가 같은 게이트를 공유한다 (어느 쪽에서 눌러도 같은 동작).
"""
from typing import Literal

from pydantic import BaseModel, Field

GateKind = Literal["analysis", "script", "images", "production"]

# 게이트가 걸리는 화면 단계
GATE_STEP: dict[str, int] = {"analysis": 1, "script": 3, "images": 5, "production": 5}


class Gate(BaseModel):
    id: str  # 6자리 코드 — Flow에서 "진행 a1b2c3" 처럼 답장할 때도 사용
    project_id: str
    project_name: str = ""
    kind: GateKind
    title: str
    summary: str = ""
    status: Literal["pending", "approved", "revised", "superseded"] = "pending"
    comment: str = ""  # 수정 요청 내용
    created_at: str
    resolved_at: str | None = None
    resolved_via: str | None = None  # ui | flow
    notified: list[str] = Field(default_factory=list)  # 알림이 나간 채널
