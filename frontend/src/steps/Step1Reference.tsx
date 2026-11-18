import { useEffect, useRef, useState } from "react";
import { api, dataUrl } from "../api";
import { AutoTextarea, ErrorBox, JobProgress, SceneDetailEditor } from "../components/common";
import { ASPECT_RATIOS, ROLES, SHOT_TYPES, fmtTime, roleLabel } from "../labels";
import type { AspectRatio, Project, ReferenceAnalysis, Segment, Status, UrlCandidate } from "../types";

const RATIO_LABEL: Record<string, string> = {
  "9:16": "세로 9:16 (릴스·쇼츠·스토리)",
  "4:5": "4:5 (피드)",
  "1:1": "정사각 1:1",
  "16:9": "가로 16:9",
};

interface Props {
  project: Project;
  status: Status | null;
  onRefresh: () => Promise<Project | null>;
  onNext: (p: Project) => void;
}

export default function Step1Reference({ project, status, onRefresh, onNext }: Props) {
  const [analysis, setAnalysis] = useState<ReferenceAnalysis | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [version, setVersion] = useState(Date.now());
  const [activeIdx, setActiveIdx] = useState<number | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const job = project.analysis_job;
  // 링크로 넣기
  const [url, setUrl] = useState("");
  const [showUrl, setShowUrl] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [candidates, setCandidates] = useState<UrlCandidate[]>([]);
  const [pickedId, setPickedId] = useState("");

  // 고르다가 페이지를 벗어났어도 받아둔 후보 목록을 다시 보여준다
  useEffect(() => {
    api.urlCandidates(project.id).then((list) => {
      setCandidates(list);
      setPickedId(list[0]?.id ?? "");
    }).catch(() => {});
  }, [project.id]);

  useEffect(() => {
    if (job.status === "running") return;
    api.getAnalysis(project.id).then((a) => {
      setAnalysis(a);
      setDirty(false);
      setVersion(Date.now());
    });
  }, [project.id, job.status]);

  const upload = async (file: File | undefined) => {
    if (!file) return;
    if (analysis && !confirm("레퍼런스를 교체하면 기존 분석과 작성된 스크립트가 초기화됩니다. 계속할까요?")) return;
    setBusy("업로드 중");
    setError("");
    try {
      await api.uploadReference(project.id, file);
      setAnalysis(null);
      await onRefresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const fromUrl = async () => {
    const link = url.trim();
    if (!link) return;
    if (analysis && !confirm("레퍼런스를 교체하면 기존 분석과 작성된 스크립트가 초기화됩니다. 계속할까요?")) return;
    setDownloading(true);
    setError("");
    try {
      const res = await api.referenceFromUrl(project.id, link);
      if (res.started) {
        setAnalysis(null);
        setUrl("");
        setShowUrl(false);
        await onRefresh();
      } else {
        const list = res.candidates ?? [];
        setCandidates(list);
        setPickedId(list[0]?.id ?? ""); // 맨 앞이 추천(세로 9:16)
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDownloading(false);
    }
  };

  const chooseCandidate = () =>
    run("분석 시작 중", async () => {
      await api.selectUrlCandidate(project.id, pickedId);
      setCandidates([]);
      setAnalysis(null);
      setUrl("");
      setShowUrl(false);
      await onRefresh();
    });

  const cancelCandidates = () =>
    run("취소 중", async () => {
      await api.cancelUrlCandidates(project.id);
      setCandidates([]);
    });

  const updateSegment = (i: number, patch: Partial<Segment>) => {
    if (!analysis) return;
    setAnalysis({ ...analysis, segments: analysis.segments.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
    setDirty(true);
  };

  const updateOverall = (patch: Partial<ReferenceAnalysis["overall"]>) => {
    if (!analysis) return;
    setAnalysis({ ...analysis, overall: { ...analysis.overall, ...patch } });
    setDirty(true);
  };

  const save = async () => {
    if (!analysis) return;
    const saved = await api.saveAnalysis(project.id, analysis);
    setAnalysis(saved);
    setDirty(false);
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

  const rerun = () =>
    run("재분석 요청 중", async () => {
      if (dirty && !confirm("수정한 내용이 재분석 결과로 덮어써집니다. 계속할까요?")) return;
      await api.rerunAnalysis(project.id);
      await onRefresh();
    });

  const next = () =>
    run("저장 중", async () => {
      if (dirty) await save();
      onNext(await api.confirmAnalysis(project.id));
    });

  const setAspect = (v: string) =>
    run("비율 변경 중", async () => {
      await api.setAspectRatio(project.id, v === "auto" ? null : (v as AspectRatio));
      await onRefresh();
    });

  const seek = (seg: Segment) => {
    setActiveIdx(seg.index);
    const v = videoRef.current;
    if (v) {
      v.currentTime = seg.start;
      v.play().catch(() => {});
    }
  };

  const onTimeUpdate = () => {
    const t = videoRef.current?.currentTime ?? 0;
    const seg = analysis?.segments.find((s) => t >= s.start && t < s.end);
    if (seg && seg.index !== activeIdx) setActiveIdx(seg.index);
  };

  const uploadZone = (
    <label className="dropzone" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); upload(e.dataTransfer.files[0]); }}>
      <input ref={fileRef} type="file" accept="video/*" hidden onChange={(e) => upload(e.target.files?.[0])} />
      <div className="dropzone-icon">▶</div>
      <strong>레퍼런스 영상을 끌어다 놓거나 클릭해서 선택하세요</strong>
      <span className="muted">
        {Math.floor((status?.max_video_sec ?? 180) / 60)}분 이하 · mp4 / mov / webm · 2초 단위로 장면·대사를 추출합니다
      </span>
    </label>
  );

  const urlRow = (
    <div className="url-row">
      <input
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && fromUrl()}
        placeholder="유튜브 · 인스타그램 · 메타 광고 라이브러리 · 틱톡 링크를 붙여넣으세요"
        disabled={downloading}
      />
      <button className="btn primary" disabled={!url.trim() || downloading} onClick={fromUrl}>
        링크로 가져오기
      </button>
    </div>
  );

  if (downloading) {
    return (
      <div className="stack">
        <JobProgress job={{ status: "running", progress: 0, message: "링크에서 영상을 받는 중입니다 (보통 10~30초)" }} title="영상 받는 중" />
      </div>
    );
  }

  if (candidates.length > 0 && job.status !== "running") {
    return (
      <div className="stack">
        {error && <ErrorBox message={error} onClose={() => setError("")} />}
        <div className="alert warn">
          이 링크에서 영상이 <b>{candidates.length}개</b> 나왔습니다 (같은 광고의 비율별 버전일 수 있습니다). 분석할 영상을 하나 고르세요.
        </div>
        <div className="cand-grid">
          {candidates.map((c, i) => (
            <label key={c.id} className={`cand-card ${pickedId === c.id ? "picked" : ""}`}>
              <video src={dataUrl(project.id, "url_candidates", c.file)} controls muted preload="metadata" />
              <div className="cand-info">
                <input type="radio" name="cand" checked={pickedId === c.id} onChange={() => setPickedId(c.id)} />
                <div>
                  <b>{RATIO_LABEL[c.aspect_ratio] ?? c.aspect_ratio}</b> {i === 0 && c.aspect_ratio === "9:16" && <span className="chip">추천</span>}
                  <div className="muted">
                    {c.width}×{c.height} · {fmtTime(c.duration)}
                    {!c.has_audio && " · 소리 없음"}
                  </div>
                </div>
              </div>
            </label>
          ))}
        </div>
        <footer className="action-bar">
          <span className="muted">고른 영상으로 장면·대사 분석을 시작합니다</span>
          <div className="row">
            <button className="btn" disabled={!!busy} onClick={cancelCandidates}>
              취소
            </button>
            <button className="btn primary" disabled={!pickedId || !!busy} onClick={chooseCandidate}>
              {busy || "이 영상으로 분석 →"}
            </button>
          </div>
        </footer>
      </div>
    );
  }

  if (job.status === "running") {
    return (
      <div className="stack">
        <JobProgress job={job} title="레퍼런스 영상 분석 중" />
        <p className="muted center">분석이 끝나면 자동으로 결과가 표시됩니다. 이 페이지를 떠나도 분석은 계속 진행됩니다.</p>
      </div>
    );
  }

  if (!analysis) {
    return (
      <div className="stack">
        {job.status === "error" && <ErrorBox message={`분석 실패: ${job.message}`} />}
        {error && <ErrorBox message={error} onClose={() => setError("")} />}
        {busy ? (
          <JobProgress job={{ status: "running", progress: 0, message: busy }} title="영상 업로드 중" />
        ) : (
          <>
            {uploadZone}
            <div className="url-or muted">또는 링크로 넣기</div>
            {urlRow}
          </>
        )}
      </div>
    );
  }

  const { source, segments, overall } = analysis;
  const effectiveRatio = project.aspect_ratio ?? source.detected_aspect_ratio;

  return (
    <div className="stack">
      {error && <ErrorBox message={error} onClose={() => setError("")} />}
      {job.status === "error" && <ErrorBox message={`재분석 실패: ${job.message}`} />}
      {analysis.mock && (
        <div className="alert warn">
          Claude가 연결되지 않아 <b>대사(음성 인식)만</b> 추출되었습니다. 장면·톤 분석은 직접 입력하거나, API 키 연결 후 [재분석]을 눌러주세요.
        </div>
      )}

      <div className="ref-layout">
        <aside className="ref-side">
          <video
            ref={videoRef}
            className="ref-video"
            src={`${dataUrl(project.id, "reference", source.file)}?v=${version}`}
            controls
            onTimeUpdate={onTimeUpdate}
          />
          <dl className="meta">
            <dt>길이</dt>
            <dd>{fmtTime(source.duration_sec)}</dd>
            <dt>해상도</dt>
            <dd>
              {source.width}×{source.height}
            </dd>
            <dt>구간</dt>
            <dd>{segments.length}개</dd>
          </dl>
          <label className="field">
            <span>영상 비율</span>
            <select value={project.aspect_ratio ?? "auto"} onChange={(e) => setAspect(e.target.value)}>
              <option value="auto">자동 (레퍼런스: {source.detected_aspect_ratio})</option>
              {ASPECT_RATIOS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <small className="muted">제작될 영상 비율: {effectiveRatio}</small>
          </label>
          <div className="row wrap">
            <button className="btn small" onClick={() => fileRef.current?.click()}>
              영상 교체
            </button>
            <button className="btn small" onClick={() => setShowUrl(!showUrl)}>
              링크로 교체
            </button>
            <button className="btn small" onClick={rerun}>
              재분석
            </button>
          </div>
          {showUrl && urlRow}
          <input ref={fileRef} type="file" accept="video/*" hidden onChange={(e) => upload(e.target.files?.[0])} />
        </aside>

        <section className="ref-main">
          <div className="section-head">
            <h2>구간별 분석</h2>
            <span className="muted">행을 클릭하면 해당 시점으로 이동합니다 · 모든 칸을 직접 수정할 수 있습니다</span>
          </div>
          <div className="seg-table">
            <div className="seg-row seg-head">
              <div>구간</div>
              <div>프레임</div>
              <div>장면</div>
              <div>대사 (한 줄 = 한 문장)</div>
              <div>역할 / 샷</div>
            </div>
            {segments.map((seg, i) => (
              <div key={seg.index} className={`seg-row ${activeIdx === seg.index ? "active" : ""}`}>
                <div className="seg-time" onClick={() => seek(seg)}>
                  <b>#{i + 1}</b>
                  <span>
                    {fmtTime(seg.start)}–{fmtTime(seg.end)}
                  </span>
                  {seg.merged_from.length > 1 && <span className="chip" title="바로 앞뒤 구간의 대사가 완전히 같아 병합됨">동일 대사 병합</span>}
                </div>
                <div className="seg-frames" onClick={() => seek(seg)}>
                  {seg.frames.slice(0, 2).map((f) => (
                    <img key={f} src={`${dataUrl(project.id, "reference", f)}?v=${version}`} alt="" loading="lazy" />
                  ))}
                </div>
                <div className="scene-cell">
                  <AutoTextarea value={seg.scene} onChange={(v) => updateSegment(i, { scene: v })} placeholder="장면 요약" />
                  <details className="detail-toggle">
                    <summary>장면 상세 (이미지 생성 기준)</summary>
                    <SceneDetailEditor detail={seg.detail} onChange={(d) => updateSegment(i, { detail: d })} />
                  </details>
                </div>
                <AutoTextarea value={seg.dialogue} onChange={(v) => updateSegment(i, { dialogue: v })} placeholder="(대사 없음)" />
                <div className="seg-selects">
                  <select value={seg.role} onChange={(e) => updateSegment(i, { role: e.target.value })}>
                    <option value="">역할 선택</option>
                    {Object.entries(ROLES).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                  <select value={seg.shot_type} onChange={(e) => updateSegment(i, { shot_type: e.target.value })}>
                    <option value="">샷 선택</option>
                    {Object.entries(SHOT_TYPES).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="overall-grid">
        <div className="card">
          <h3>말투</h3>
          <div className="grid2">
            <label className="field">
              <span>존댓말/반말</span>
              <input value={overall.tone.speech_level} onChange={(e) => updateOverall({ tone: { ...overall.tone, speech_level: e.target.value } })} />
            </label>
            <label className="field">
              <span>속도·리듬</span>
              <input value={overall.tone.pace} onChange={(e) => updateOverall({ tone: { ...overall.tone, pace: e.target.value } })} />
            </label>
          </div>
          <label className="field">
            <span>말버릇 (쉼표로 구분)</span>
            <input
              value={overall.tone.habits.join(", ")}
              onChange={(e) =>
                updateOverall({ tone: { ...overall.tone, habits: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) } })
              }
            />
          </label>
          <label className="field">
            <span>설명</span>
            <AutoTextarea minRows={2} value={overall.tone.description} onChange={(v) => updateOverall({ tone: { ...overall.tone, description: v } })} />
          </label>
        </div>

        <div className="card">
          <h3>화자 페르소나</h3>
          <div className="grid2">
            <label className="field">
              <span>연령대</span>
              <input value={overall.persona.age} onChange={(e) => updateOverall({ persona: { ...overall.persona, age: e.target.value } })} />
            </label>
            <label className="field">
              <span>성별</span>
              <input value={overall.persona.gender} onChange={(e) => updateOverall({ persona: { ...overall.persona, gender: e.target.value } })} />
            </label>
          </div>
          <label className="field">
            <span>캐릭터</span>
            <AutoTextarea value={overall.persona.character} onChange={(v) => updateOverall({ persona: { ...overall.persona, character: v } })} />
          </label>
          <label className="field">
            <span>신뢰 근거</span>
            <AutoTextarea value={overall.persona.credibility} onChange={(v) => updateOverall({ persona: { ...overall.persona, credibility: v } })} />
          </label>
        </div>

        <div className="card">
          <h3>전체 컨셉</h3>
          <AutoTextarea minRows={4} value={overall.concept} onChange={(v) => updateOverall({ concept: v })} />
          <h4>비주얼 스타일 (전체 장면 공통)</h4>
          <AutoTextarea minRows={3} value={overall.visual_style} onChange={(v) => updateOverall({ visual_style: v })} placeholder="촬영 방식 · 색감 · 편집 리듬 · 자막 스타일" />
          {overall.structure.length > 0 && (
            <>
              <h4>구성 흐름</h4>
              <ol className="structure">
                {overall.structure.map((p, i) => (
                  <li key={i}>
                    <span className="chip">{roleLabel(p.role)}</span> {fmtTime(p.start)}–{fmtTime(p.end)} <span className="muted">{p.summary}</span>
                  </li>
                ))}
              </ol>
            </>
          )}
        </div>
      </section>

      <footer className="action-bar">
        <span className="muted">{dirty ? "수정한 내용이 있습니다" : analysis.confirmed ? "확정된 분석입니다" : "추출 결과를 확인한 뒤 진행하세요"}</span>
        <div className="row">
          <button className="btn" disabled={!dirty || !!busy} onClick={() => run("저장 중", save)}>
            저장
          </button>
          <button className="btn primary" disabled={!!busy} onClick={next}>
            {busy || "진행 →"}
          </button>
        </div>
      </footer>
    </div>
  );
}
