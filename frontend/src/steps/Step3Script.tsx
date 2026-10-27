import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import ChatPanel from "../components/ChatPanel";
import { AutoTextarea, ErrorBox, JobProgress, useDebouncedEffect } from "../components/common";
import { ASPECT_RATIOS, SYLLABLES_PER_SEC, fmtTime, roleLabel, splitSentences, syllables } from "../labels";
import type { AspectRatio, Project, ReferenceAnalysis, Scene, Script, Status } from "../types";

interface Props {
  project: Project;
  status: Status | null;
  onRefresh: () => Promise<Project | null>;
  onNext: (p: Project) => void;
}

type SaveState = "saved" | "dirty" | "saving" | "error";

export default function Step3Script({ project, status, onRefresh, onNext }: Props) {
  const [script, setScript] = useState<Script | null>(null);
  const [analysis, setAnalysis] = useState<ReferenceAnalysis | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [busy, setBusy] = useState("");
  const [regenId, setRegenId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const latest = useRef<Script | null>(null);
  const job = project.script_job;
  const configured = !!status?.claude_configured;
  const locked = script?.status === "final";

  const loadScript = useCallback(async () => {
    const s = await api.getScript(project.id);
    setScript(s);
    latest.current = s;
    setSaveState("saved");
  }, [project.id]);

  useEffect(() => {
    api.getAnalysis(project.id).then(setAnalysis);
  }, [project.id]);

  useEffect(() => {
    if (job.status !== "running") loadScript();
  }, [job.status, loadScript]);

  const flush = useCallback(async () => {
    if (!latest.current || saveState === "saved") return;
    setSaveState("saving");
    try {
      await api.saveScript(project.id, latest.current);
      setSaveState("saved");
    } catch (e) {
      setSaveState("error");
      throw e;
    }
  }, [project.id, saveState]);

  useDebouncedEffect(() => {
    if (saveState === "dirty") flush().catch((e) => setError((e as Error).message));
  }, [script], 800);

  const edit = (next: Script) => {
    setScript(next);
    latest.current = next;
    setSaveState("dirty");
  };

  const editScene = (id: string, patch: Partial<Scene>) => {
    if (!script) return;
    edit({ ...script, scenes: script.scenes.map((s) => (s.id === id ? { ...s, ...patch } : s)) });
  };

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const regenerateAll = () =>
    run("재생성 요청 중", async () => {
      if (script && !confirm("현재 스크립트와 대화 기록이 새로 작성된 스크립트로 바뀝니다. 계속할까요?")) return;
      await api.generateScript(project.id);
      await onRefresh();
    });

  const regenerateScene = async (scene: Scene) => {
    const instruction = prompt(`장면을 새로 작성합니다. 추가 요청이 있으면 입력하세요 (없으면 비워두고 확인)`, "");
    if (instruction === null) return;
    setRegenId(scene.id);
    setError("");
    try {
      await flush();
      const s = await api.regenerateScene(project.id, scene.id, instruction);
      setScript(s);
      latest.current = s;
      setSaveState("saved");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRegenId(null);
    }
  };

  const setAspect = (v: AspectRatio) =>
    run("비율 변경 중", async () => {
      await flush();
      await api.setAspectRatio(project.id, v);
      await loadScript();
      await onRefresh();
    });

  const reopen = () =>
    run("편집 여는 중", async () => {
      const s = await api.reopen(project.id);
      setScript(s);
      latest.current = s;
    });

  const finalize = () =>
    run("확정 중", async () => {
      await flush();
      onNext(await api.finalize(project.id));
    });

  if (job.status === "running") {
    return <JobProgress job={job} title="자사 제품 스크립트 작성 중" />;
  }

  if (!script) {
    return (
      <div className="stack">
        {job.status === "error" && <ErrorBox message={`스크립트 작성 실패: ${job.message}`} />}
        {error && <ErrorBox message={error} onClose={() => setError("")} />}
        <div className="empty-card">
          <p>레퍼런스 구조와 제품 정보를 바탕으로 새 스크립트를 작성합니다.</p>
          <button className="btn primary" disabled={!!busy} onClick={regenerateAll}>
            스크립트 생성
          </button>
        </div>
      </div>
    );
  }

  const refSeg = (i: number | null) => (i === null ? undefined : analysis?.segments.find((s) => s.index === i));

  return (
    <div className="stack">
      {error && <ErrorBox message={error} onClose={() => setError("")} />}
      {job.status === "error" && <ErrorBox message={`스크립트 재생성 실패: ${job.message}`} />}
      {script.mock && (
        <div className="alert warn">
          Claude 미연결 상태라 <b>레퍼런스 대사를 그대로 복사한 초안</b>입니다. 직접 수정하거나, API 키 연결 후 [전체 재생성]을 눌러주세요.
        </div>
      )}
      {locked && (
        <div className="alert ok row between">
          <span>확정된 스크립트입니다. 수정하려면 편집을 다시 여세요.</span>
          <button className="btn small" onClick={reopen}>
            편집 다시 열기
          </button>
        </div>
      )}

      <div className="script-layout">
        <section className="script-main">
          <div className="card script-meta">
            <label className="field grow">
              <span>제목</span>
              <input value={script.meta.title} disabled={locked} onChange={(e) => edit({ ...script, meta: { ...script.meta, title: e.target.value } })} />
            </label>
            <label className="field">
              <span>영상 비율</span>
              <select value={script.meta.aspect_ratio} disabled={locked || !!busy} onChange={(e) => setAspect(e.target.value as AspectRatio)}>
                {ASPECT_RATIOS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <div className="voice-grid">
              {(
                [
                  ["persona", "화자"],
                  ["speech_level", "말투"],
                  ["pace", "속도"],
                  ["emotion", "감정"],
                ] as const
              ).map(([k, label]) => (
                <label key={k} className="field">
                  <span>{label}</span>
                  <input
                    value={script.voice[k]}
                    disabled={locked}
                    onChange={(e) => edit({ ...script, voice: { ...script.voice, [k]: e.target.value } })}
                  />
                </label>
              ))}
            </div>
          </div>

          <div className="section-head">
            <h2>장면 {script.scenes.length}개</h2>
            <div className="row">
              <span className={`save-state ${saveState}`}>
                {{ saved: "저장됨", dirty: "수정 중…", saving: "저장 중…", error: "저장 실패" }[saveState]}
              </span>
              <button className="btn small" disabled={locked || !!busy} onClick={regenerateAll}>
                전체 재생성
              </button>
            </div>
          </div>

          {script.scenes.map((scene, i) => {
            const ref = refSeg(scene.ref_segment);
            const dur = scene.end - scene.start;
            const limit = Math.round(dur * SYLLABLES_PER_SEC);
            const count = syllables(scene.dialogue);
            const refLines = ref ? splitSentences(ref.dialogue) : [];
            const myLines = splitSentences(scene.dialogue);
            return (
              <article key={scene.id} className={`scene-card ${regenId === scene.id ? "loading" : ""}`}>
                <header className="scene-head">
                  <span className="scene-no">#{String(i + 1).padStart(2, "0")}</span>
                  <span className="scene-time">
                    {fmtTime(scene.start)}–{fmtTime(scene.end)}
                  </span>
                  {scene.role && <span className="chip">{roleLabel(scene.role)}</span>}
                  <button
                    className="btn small ghost push"
                    disabled={locked || !configured || regenId !== null}
                    title={configured ? "이 장면 대사만 새로 작성" : "Claude 연결 후 사용 가능"}
                    onClick={() => regenerateScene(scene)}
                  >
                    {regenId === scene.id ? "작성 중…" : "↻ 이 장면 재생성"}
                  </button>
                </header>

                <div className="dialogue-pair">
                  <div className="dialogue-ref">
                    <span className="pair-label">레퍼런스 대사</span>
                    {refLines.length ? (
                      <ol className="sentence-list">
                        {refLines.map((line, n) => (
                          <li key={n}>{line}</li>
                        ))}
                      </ol>
                    ) : (
                      <span className="muted">(대사 없음)</span>
                    )}
                  </div>
                  <label className="dialogue-mine">
                    <span className="pair-label">
                      자사 대사 · 한 줄에 한 문장
                      <small className={count > limit ? "over" : "muted"}>
                        {" "}
                        {count}/{limit}음절
                      </small>
                      <small className={ref && myLines.length !== refLines.length ? "over" : "muted"}>
                        {" "}
                        · {myLines.length}문장{ref ? ` (레퍼런스 ${refLines.length})` : ""}
                      </small>
                    </span>
                    <AutoTextarea className="big" value={scene.dialogue} disabled={locked} onChange={(v) => editScene(scene.id, { dialogue: v })} placeholder="(대사 없음)" />
                  </label>
                </div>
              </article>
            );
          })}
        </section>

        <ChatPanel
          projectId={project.id}
          configured={configured}
          launcher={status?.launcher ?? "2_실행하기"}
          locked={locked}
          scenes={script.scenes}
          beforeApply={flush}
          onApplied={loadScript}
        />
      </div>

      <footer className="action-bar">
        <span className="muted">마음에 들면 바로 확정하세요. 확정 후 TXT 저장 · 복사가 가능합니다.</span>
        <button className="btn primary" disabled={!!busy || locked} onClick={finalize}>
          {busy || "기획안 확정 →"}
        </button>
      </footer>
    </div>
  );
}
