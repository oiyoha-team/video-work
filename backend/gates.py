"""승인 게이트 저장소. 게이트를 열고(알림 발송) 닫는 것만 담당한다.

[진행]/[수정]을 눌렀을 때 실제로 무엇을 실행할지는 workflow.resolve_gate()가 정한다.
"""
import uuid

import notify
from planning import store
from schemas import Gate, GateKind

_TITLES: dict[str, str] = {
    "analysis": "레퍼런스 분석 완료 — 추출 결과를 확인해 주세요",
    "script": "스크립트 작성 완료 — 기획안을 확정할까요?",
    "images": "장면 이미지 생성 완료 — 영상화를 진행할까요?",
    "production": "영상 클립·음성 준비 완료 — 확정하고 결과물을 받을까요?",
}


def open_gate(project_id: str, kind: GateKind, summary: str, title: str | None = None) -> Gate:
    with store.lock(project_id):
        project = store.get_project(project_id)
        gates = store.get_gates(project_id)
        for g in gates:
            if g.kind == kind and g.status == "pending":
                g.status = "superseded"
        gate = Gate(
            id=uuid.uuid4().hex[:6],
            project_id=project_id,
            project_name=project.name,
            kind=kind,
            title=title or _TITLES[kind],
            summary=summary,
            created_at=store.now(),
        )
        gates.append(gate)
        store.save_gates(project_id, gates)
    gate.notified = notify.dispatch(gate)
    if gate.notified:
        _update(project_id, gate.id, notified=gate.notified)
    return gate


def _update(project_id: str, gate_id: str, **changes) -> Gate:
    with store.lock(project_id):
        gates = store.get_gates(project_id)
        gate = next((g for g in gates if g.id == gate_id), None)
        if gate is None:
            raise FileNotFoundError(f"게이트 {gate_id}")
        for k, v in changes.items():
            setattr(gate, k, v)
        store.save_gates(project_id, gates)
        return gate


def get_pending(project_id: str, gate_id: str) -> Gate:
    gate = next((g for g in store.get_gates(project_id) if g.id == gate_id), None)
    if gate is None:
        raise FileNotFoundError(f"게이트 {gate_id}")
    if gate.status != "pending":
        raise ValueError("이미 처리된 알림입니다.")
    return gate


def mark(project_id: str, gate_id: str, status: str, via: str, comment: str = "") -> Gate:
    return _update(project_id, gate_id, status=status, resolved_via=via, resolved_at=store.now(), comment=comment)


def close_kind(project_id: str, kind: GateKind, via: str = "ui") -> None:
    """화면에서 직접 [진행]을 누른 경우, 같은 종류의 대기 중 게이트를 승인 처리한다."""
    with store.lock(project_id):
        gates = store.get_gates(project_id)
        changed = False
        for g in gates:
            if g.kind == kind and g.status == "pending":
                g.status, g.resolved_via, g.resolved_at = "approved", via, store.now()
                changed = True
        if changed:
            store.save_gates(project_id, gates)


def find(gate_id: str) -> Gate:
    """프로젝트를 모르는 상태(예: Flow 답장)에서 게이트 코드로 찾기."""
    for project in store.list_projects():
        for g in store.get_gates(project.id):
            if g.id == gate_id:
                return g
    raise FileNotFoundError(f"게이트 {gate_id}")


def all_pending() -> list[Gate]:
    out = [g for p in store.list_projects() for g in store.get_gates(p.id) if g.status == "pending"]
    return sorted(out, key=lambda g: g.created_at, reverse=True)
