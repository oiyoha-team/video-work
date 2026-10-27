import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox } from "../components/common";
import type { Project, Script } from "../types";

interface Props {
  project: Project;
  onBack: () => void;
  onNext: (p: Project) => void;
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // clipboard API를 못 쓰는 환경 대비
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}

export default function Step4Export({ project, onBack, onNext }: Props) {
  const [script, setScript] = useState<Script | null>(null);
  const [text, setText] = useState("");
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getScript(project.id).then(setScript);
    api.scriptText(project.id).then(setText).catch((e) => setError((e as Error).message));
  }, [project.id]);

  const download = () => {
    const name = (script?.meta.title || project.name).replace(/[\\/:*?"<>|]/g, "_");
    const url = URL.createObjectURL(new Blob(["﻿" + text], { type: "text/plain;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${name}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const copy = async () => {
    await copyText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  const reopen = async () => {
    try {
      await api.reopen(project.id);
      onBack();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const finalize = async () => {
    try {
      await api.finalize(project.id);
      setScript(await api.getScript(project.id));
      setText(await api.scriptText(project.id));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const toProduction = async () => {
    try {
      onNext(await api.startProduction(project.id));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const final = script?.status === "final";

  return (
    <div className="stack">
      {error && <ErrorBox message={error} onClose={() => setError("")} />}
      <section className="card export-head">
        <div>
          <h2>{script?.meta.title || "기획안"}</h2>
          <p className="muted">
            {final ? "✓ 확정된 기획안입니다." : "아직 확정되지 않았습니다."} 장면 {script?.scenes.length ?? 0}개 · 비율{" "}
            {script?.meta.aspect_ratio}
          </p>
        </div>
        <div className="row wrap">
          {script && !final && (
            <button className="btn" onClick={finalize}>
              기획안 확정
            </button>
          )}
          <button className="btn" onClick={download} disabled={!text}>
            TXT 저장
          </button>
          <button className="btn primary" onClick={copy} disabled={!text}>
            {copied ? "✓ 복사됨" : "전체 복사"}
          </button>
        </div>
      </section>

      <pre className="script-text">{text}</pre>

      <footer className="action-bar">
        <button className="btn ghost" onClick={final ? reopen : onBack}>
          ← {final ? "편집 다시 열기" : "스크립트로 돌아가기"}
        </button>
        <button className="btn primary" disabled={!final} title={final ? "비주얼 · 사운드 제작을 동시에 시작합니다" : "기획안을 먼저 확정하세요"} onClick={toProduction}>
          영상 제작으로 넘기기 →
        </button>
      </footer>
    </div>
  );
}
