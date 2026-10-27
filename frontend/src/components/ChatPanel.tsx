import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ChatChange, ChatMessage, Scene } from "../types";

interface Props {
  projectId: string;
  configured: boolean;
  launcher: string;
  locked: boolean;
  scenes: Scene[];
  beforeApply: () => Promise<void>;
  onApplied: () => Promise<void>;
}

const FIELD_LABELS: [keyof ChatChange, string, (s: Scene) => string][] = [
  ["dialogue", "대사", (s) => s.dialogue],
];

const EXAMPLES = ["훅을 더 자극적으로 바꿔줘", "3번 장면에 USP 하나 더 녹여줘", "CTA를 프로모션 중심으로", "전체적으로 더 친근한 말투로"];

export default function ChatPanel({ projectId, configured, launcher, locked, scenes, beforeApply, onApplied }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const sceneById = Object.fromEntries(scenes.map((s, i) => [s.id, { scene: s, no: i + 1 }]));

  useEffect(() => {
    api.getChat(projectId).then(setMessages);
  }, [projectId]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  const send = async (text = input) => {
    const msg = text.trim();
    if (!msg || sending) return;
    setSending(true);
    setError("");
    setInput("");
    setMessages((m) => [...m, { id: "pending", role: "user", content: msg }]);
    try {
      await beforeApply();
      setMessages(await api.sendChat(projectId, msg));
    } catch (e) {
      setError((e as Error).message);
      setMessages((m) => m.filter((x) => x.id !== "pending"));
      setInput(msg);
    } finally {
      setSending(false);
    }
  };

  const resolve = async (id: string, apply: boolean) => {
    setError("");
    try {
      if (apply) await beforeApply();
      setMessages(await api.resolveChat(projectId, id, apply));
      if (apply) await onApplied();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <aside className="chat">
      <header className="chat-head">
        <span className="claude-dot" />
        <strong>Claude와 스크립트 다듬기</strong>
      </header>

      {!configured && (
        <div className="alert warn small">
          API 키가 아직 연결되지 않았습니다. <code>.env</code>에 <code>ANTHROPIC_API_KEY</code>를 넣고 <code>{launcher}</code>을(를) 다시 실행하면 대화로 수정할 수 있습니다.
        </div>
      )}

      <div className="chat-list" ref={listRef}>
        {messages.length === 0 && (
          <div className="chat-empty">
            <p className="muted">수정하고 싶은 부분을 말로 요청하세요. Claude가 변경안을 제안하면 [적용]을 눌러야 반영됩니다.</p>
            <div className="chips">
              {EXAMPLES.map((ex) => (
                <button key={ex} className="chip-btn" disabled={!configured || locked} onClick={() => send(ex)}>
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`bubble ${m.role}`}>
            <div className="bubble-text">{m.content}</div>
            {m.changes && m.changes.length > 0 && (
              <div className={`proposal ${m.status}`}>
                {m.changes.map((c) => {
                  const ref = sceneById[c.scene_id];
                  const diffs = FIELD_LABELS.filter(([k, , get]) => ref && (c[k] as string) !== get(ref.scene));
                  return (
                    <div key={c.scene_id} className="change">
                      <div className="change-head">장면 #{ref ? String(ref.no).padStart(2, "0") : c.scene_id}</div>
                      {diffs.length === 0 && <div className="muted small">변경 없음</div>}
                      {diffs.map(([k, label, get]) => (
                        <div key={k} className="diff">
                          <span className="diff-label">{label}</span>
                          {m.status === "pending" && <del>{get(ref!.scene) || "(비어 있음)"}</del>}
                          <ins>{(c[k] as string) || "(비어 있음)"}</ins>
                        </div>
                      ))}
                    </div>
                  );
                })}
                {m.status === "pending" ? (
                  <div className="row end">
                    <button className="btn small ghost" onClick={() => resolve(m.id, false)}>
                      무시
                    </button>
                    <button className="btn small primary" disabled={locked} onClick={() => resolve(m.id, true)}>
                      적용
                    </button>
                  </div>
                ) : (
                  <div className="muted small right">{m.status === "applied" ? "✓ 적용됨" : "무시함"}</div>
                )}
              </div>
            )}
          </div>
        ))}
        {sending && (
          <div className="bubble assistant">
            <div className="typing">
              <span />
              <span />
              <span />
            </div>
          </div>
        )}
      </div>

      {error && <div className="alert error small">{error}</div>}

      <div className="chat-input">
        <textarea
          rows={2}
          value={input}
          placeholder={locked ? "확정된 스크립트입니다" : "예: 2번 장면 대사를 더 짧게"}
          disabled={sending || locked}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button className="btn primary" disabled={sending || locked || !input.trim()} onClick={() => send()}>
          전송
        </button>
      </div>
    </aside>
  );
}
