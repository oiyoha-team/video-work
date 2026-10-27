import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { GATE_STEP, JOB_FIELDS } from "./types";
import type { Gate, Project, Status } from "./types";
import { ErrorBox } from "./components/common";
import { GateBanner, NotificationCenter } from "./components/Gates";
import Step1Reference from "./steps/Step1Reference";
import Step2Product from "./steps/Step2Product";
import Step3Script from "./steps/Step3Script";
import Step4Export from "./steps/Step4Export";
import Step5Production from "./steps/Step5Production";
import Step6Download from "./steps/Step6Download";

const STEPS = [
  { n: 1, label: "레퍼런스 분석", group: "기획" },
  { n: 2, label: "제품 정보", group: "기획" },
  { n: 3, label: "스크립트 작성", group: "기획" },
  { n: 4, label: "기획 확정", group: "기획" },
  { n: 5, label: "영상 제작", group: "영상" },
  { n: 6, label: "결과물 다운로드", group: "영상" },
];
const LAST_STEP = STEPS.length;
const LAST_PROJECT_KEY = "oiyoha:lastProject";

function readLastProject(): string | null {
  try {
    return localStorage.getItem(LAST_PROJECT_KEY);
  } catch {
    return null;
  }
}

function writeLastProject(id: string | null) {
  try {
    if (id) localStorage.setItem(LAST_PROJECT_KEY, id);
    else localStorage.removeItem(LAST_PROJECT_KEY);
  } catch {
    /* 저장소 사용 불가 */
  }
}

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [view, setView] = useState(1);
  const [error, setError] = useState("");
  const [newName, setNewName] = useState("");
  const [pendingGates, setPendingGates] = useState<Gate[]>([]);
  const [projectGates, setProjectGates] = useState<Gate[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const initialHash = useRef(new URLSearchParams(location.hash.slice(1)));
  const [ready, setReady] = useState(false);

  const refreshProjects = useCallback(() => api.listProjects().then(setProjects).catch(() => {}), []);
  const refreshGates = useCallback(() => {
    api.pendingGates().then(setPendingGates).catch(() => {});
  }, []);

  const openProject = (p: Project, step?: number) => {
    setProject(p);
    setView(Math.min(step ?? p.step, p.step, LAST_STEP));
    writeLastProject(p.id);
  };

  const closeProject = () => {
    setProject(null);
    writeLastProject(null);
    refreshProjects();
  };

  useEffect(() => {
    api.status().then(setStatus).catch(() => setError("백엔드 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요."));
    api
      .listProjects()
      .then((list) => {
        setProjects(list);
        // URL(#p=<id>&s=<step>) → 마지막으로 연 기획안 순으로 복원
        const hash = initialHash.current;
        const target = hash.get("p") ?? readLastProject();
        const found = list.find((p) => p.id === target);
        if (found) openProject(found, Number(hash.get("s")) || undefined);
      })
      .finally(() => setReady(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!ready) return;
    const hash = project ? `#p=${project.id}&s=${view}` : "";
    if (location.hash !== hash) history.replaceState(null, "", hash || location.pathname);
  }, [ready, project?.id, view]);

  // 승인 대기 알림 폴링 (Flow로 나가는 요청과 동일)
  useEffect(() => {
    refreshGates();
    const t = setInterval(refreshGates, 4000);
    return () => clearInterval(t);
  }, [refreshGates]);

  useEffect(() => {
    if (project) api.projectGates(project.id).then(setProjectGates).catch(() => {});
  }, [project?.id, project?.updated_at, pendingGates.length]);

  const refreshProject = useCallback(async () => {
    if (!project) return null;
    const p = await api.getProject(project.id);
    setProject(p);
    return p;
  }, [project]);

  // 백그라운드 작업 중에는 상태를 폴링
  const running = !!project && JOB_FIELDS.some((f) => project[f].status === "running");
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => {
      refreshProject().catch(() => {});
    }, 2000);
    return () => clearInterval(t);
  }, [running, refreshProject]);

  const create = async () => {
    try {
      const p = await api.createProject(newName.trim());
      setNewName("");
      await refreshProjects();
      openProject(p);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const remove = async (p: Project) => {
    if (!confirm(`'${p.name}' 기획안을 삭제할까요? 업로드한 영상과 만든 결과물이 모두 삭제됩니다.`)) return;
    await api.deleteProject(p.id);
    if (project?.id === p.id) closeProject();
    refreshProjects();
    refreshGates();
  };

  const advance = (p: Project, next: number) => {
    setProject(p);
    setView(next);
    refreshProjects();
    refreshGates();
  };

  // 알림 센터 / 배너에서 [진행]·[수정]
  const resolveGate = async (g: Gate, action: "approve" | "revise", comment: string) => {
    try {
      await api.resolveGate(g.project_id, g.id, action, comment);
      const p = await api.getProject(g.project_id);
      const next = action === "approve" ? Math.min(p.step, LAST_STEP) : GATE_STEP[g.kind];
      setProject(p);
      setView(next);
      writeLastProject(p.id);
      setReloadKey((k) => k + 1);
      refreshGates();
      refreshProjects();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const openGate = async (g: Gate) => {
    const p = await api.getProject(g.project_id);
    openProject(p, GATE_STEP[g.kind]);
    setReloadKey((k) => k + 1);
  };

  const stepGates = projectGates.filter((g) => GATE_STEP[g.kind] === view);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand" onClick={closeProject}>
          <span className="brand-mark">O</span>
          <div>
            <div className="brand-title">오이요하 퍼포먼스 영상 자동화</div>
            <div className="brand-sub">기획 자동화 → 영상 자동화</div>
          </div>
        </div>
        {project && <div className="project-name">{project.name}</div>}
        <div className="topbar-right">
          {status && (
            <span className={`badge ${status.claude_configured ? "ok" : "warn"}`} title={status.claude_model}>
              {status.claude_configured ? "Claude 연결됨" : "Claude 미연결"}
            </span>
          )}
          <NotificationCenter gates={pendingGates} flowEnabled={!!status?.flow_enabled} onResolve={resolveGate} onOpen={openGate} />
          {project && (
            <button className="btn ghost" onClick={closeProject}>
              기획안 목록
            </button>
          )}
        </div>
      </header>

      {error && <ErrorBox message={error} onClose={() => setError("")} />}

      {!project ? (
        <main className="home">
          <section className="card">
            <h2>새 기획안 만들기</h2>
            <div className="row">
              <input
                className="grow"
                placeholder="기획안 이름 (예: 시카세럼 여름 캠페인 #1)"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !e.nativeEvent.isComposing && create()}
              />
              <button className="btn primary" onClick={create}>
                만들기
              </button>
            </div>
          </section>
          <section className="card">
            <h2>기획안 목록</h2>
            {projects.length === 0 ? (
              <p className="muted">아직 기획안이 없습니다.</p>
            ) : (
              <ul className="project-list">
                {projects.map((p) => {
                  const waiting = pendingGates.filter((g) => g.project_id === p.id).length;
                  return (
                    <li key={p.id}>
                      <button className="project-item" onClick={() => openProject(p)}>
                        <span className="row">
                          <strong>{p.name}</strong>
                          {p.completed && <span className="chip">제작 완료</span>}
                          {waiting > 0 && <span className="chip warn-chip">승인 대기 {waiting}</span>}
                        </span>
                        <span className="muted">
                          {STEPS[Math.min(p.step, LAST_STEP) - 1].label} 단계 · {p.updated_at.replace("T", " ")}
                        </span>
                      </button>
                      <button className="icon-btn" title="삭제" onClick={() => remove(p)}>
                        ×
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
          {status && (
            <section className="card env-card">
              <h3>실행 환경</h3>
              <dl className="meta">
                <dt>OS</dt>
                <dd>{{ windows: "Windows", mac: "macOS", linux: "Linux" }[status.platform]}</dd>
                <dt>실행 파일</dt>
                <dd>{status.launcher}</dd>
                <dt>음성 인식</dt>
                <dd>
                  {status.stt_engine} ({status.whisper_model})
                </dd>
                <dt>이미지·영상</dt>
                <dd>{status.visual_engine}</dd>
                <dt>음성 합성</dt>
                <dd>{status.sound_engine}</dd>
                <dt>Flow 알림</dt>
                <dd>{status.flow_enabled ? "연동됨" : "미연동 (앱 알림만)"}</dd>
              </dl>
            </section>
          )}
        </main>
      ) : (
        <>
          <nav className="stepper">
            {STEPS.map((s, i) => (
              <div key={s.n} className="step-wrap">
                {i > 0 && STEPS[i - 1].group !== s.group && <span className="step-divider">영상 자동화</span>}
                <button
                  className={`step ${view === s.n ? "active" : ""} ${s.n <= project.step ? "unlocked" : ""} ${
                    s.n < project.step || (s.n === LAST_STEP && project.completed) ? "done" : ""
                  }`}
                  disabled={s.n > project.step}
                  onClick={() => s.n <= project.step && setView(s.n)}
                >
                  <span className="step-num">{s.n < project.step || (s.n === LAST_STEP && project.completed) ? "✓" : s.n}</span>
                  {s.label}
                  {pendingGates.some((g) => g.project_id === project.id && GATE_STEP[g.kind] === s.n) && <span className="step-alert" title="승인 대기" />}
                </button>
              </div>
            ))}
          </nav>

          <main className="content">
            <GateBanner gates={stepGates} onResolve={resolveGate} />
            <div key={`${view}-${reloadKey}`}>
              {view === 1 && <Step1Reference project={project} status={status} onRefresh={refreshProject} onNext={(p) => advance(p, 2)} />}
              {view === 2 && <Step2Product project={project} onNext={(p) => advance(p, 3)} />}
              {view === 3 && <Step3Script project={project} status={status} onRefresh={refreshProject} onNext={(p) => advance(p, 4)} />}
              {view === 4 && <Step4Export project={project} onBack={() => setView(3)} onNext={(p) => advance(p, 5)} />}
              {view === 5 && <Step5Production project={project} status={status} onRefresh={refreshProject} onNext={(p) => advance(p, 6)} />}
              {view === 6 && <Step6Download project={project} />}
            </div>
          </main>
        </>
      )}
    </div>
  );
}
