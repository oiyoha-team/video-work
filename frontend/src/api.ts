import type {
  AspectRatio,
  ChatMessage,
  Estimate,
  ExportList,
  Gate,
  LibraryItem,
  Product,
  Production,
  Project,
  ReferenceAnalysis,
  Script,
  Status,
  TTSSettings,
  TypecastVoice,
  UrlCandidate,
  VoicesMeta,
} from "./types";

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") detail = data.detail;
    } catch {
      /* 본문이 JSON이 아닌 경우 */
    }
    throw new Error(detail);
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

const P = (pid: string) => `/api/projects/${pid}`;

function files(field: string, list: FileList | File[]): FormData {
  const fd = new FormData();
  Array.from(list).forEach((f) => fd.append(field, f));
  return fd;
}

export const api = {
  status: () => request<Status>("GET", "/api/status"),

  listProjects: () => request<Project[]>("GET", "/api/projects"),
  createProject: (name: string) => request<Project>("POST", "/api/projects", { name }),
  getProject: (pid: string) => request<Project>("GET", P(pid)),
  deleteProject: (pid: string) => request("DELETE", P(pid)),
  setAspectRatio: (pid: string, aspect_ratio: AspectRatio | null) =>
    request<Project>("PUT", `${P(pid)}/aspect-ratio`, { aspect_ratio }),

  // Step 1
  uploadReference: (pid: string, file: File) => request("POST", `${P(pid)}/reference`, files("file", [file])),
  referenceFromUrl: (pid: string, url: string) =>
    request<{ started: boolean; candidates?: UrlCandidate[] }>("POST", `${P(pid)}/reference/url`, { url }),
  urlCandidates: (pid: string) => request<UrlCandidate[]>("GET", `${P(pid)}/reference/url/candidates`),
  selectUrlCandidate: (pid: string, id: string) => request("POST", `${P(pid)}/reference/url/select`, { id }),
  cancelUrlCandidates: (pid: string) => request("DELETE", `${P(pid)}/reference/url/candidates`),
  rerunAnalysis: (pid: string) => request("POST", `${P(pid)}/analyze`),
  getAnalysis: (pid: string) => request<ReferenceAnalysis | null>("GET", `${P(pid)}/analysis`),
  saveAnalysis: (pid: string, a: ReferenceAnalysis) => request<ReferenceAnalysis>("PUT", `${P(pid)}/analysis`, a),
  confirmAnalysis: (pid: string) => request<Project>("POST", `${P(pid)}/analysis/confirm`),

  // Step 2
  getProduct: (pid: string) => request<Product>("GET", `${P(pid)}/product`),
  saveProduct: (pid: string, p: Product) => request<Product>("PUT", `${P(pid)}/product`, p),
  uploadProductImages: (pid: string, kind: "styled" | "cutout", list: FileList) =>
    request<Product>("POST", `${P(pid)}/product/images/${kind}`, files("files", list)),
  deleteProductImage: (pid: string, kind: string, id: string) =>
    request<Product>("DELETE", `${P(pid)}/product/images/${kind}/${id}`),
  saveToLibrary: (pid: string, overwrite: boolean, template_name = "") =>
    request<Product>("POST", `${P(pid)}/product/save-to-library`, { overwrite, template_name }),
  renameLibraryItem: (libraryId: string, name: string) =>
    request<{ library_id: string; name: string }>("PUT", `/api/products/${libraryId}/name`, { name }),
  loadFromLibrary: (pid: string, libraryId: string) =>
    request<Product>("POST", `${P(pid)}/product/load/${libraryId}`),
  confirmProduct: (pid: string) => request<Project>("POST", `${P(pid)}/product/confirm`),
  listLibrary: () => request<LibraryItem[]>("GET", "/api/products"),
  deleteLibraryItem: (libraryId: string) => request("DELETE", `/api/products/${libraryId}`),
  importProduct: (pid: string, file: File) =>
    request<{ fields: Partial<Product>; method: string; warning?: string; images_added: number; images_skipped: number; product: Product }>(
      "POST",
      `${P(pid)}/product/import`,
      files("file", [file]),
    ),
  parseMarkdown: (file: File) =>
    request<{ fields: Partial<Product>; method: string; warning?: string }>(
      "POST",
      "/api/products/parse-md",
      files("file", [file]),
    ),

  // Step 3
  getScript: (pid: string) => request<Script | null>("GET", `${P(pid)}/script`),
  saveScript: (pid: string, s: Script) => request<Script>("PUT", `${P(pid)}/script`, s),
  generateScript: (pid: string) => request("POST", `${P(pid)}/script/generate`),
  regenerateScene: (pid: string, sceneId: string, instruction: string) =>
    request<Script>("POST", `${P(pid)}/script/scenes/${sceneId}/regenerate`, { instruction }),
  getChat: (pid: string) => request<ChatMessage[]>("GET", `${P(pid)}/chat`),
  sendChat: (pid: string, message: string) => request<ChatMessage[]>("POST", `${P(pid)}/chat`, { message }),
  resolveChat: (pid: string, messageId: string, apply: boolean) =>
    request<ChatMessage[]>("POST", `${P(pid)}/chat/${messageId}/resolve`, { apply }),

  // Step 4
  finalize: (pid: string) => request<Project>("POST", `${P(pid)}/script/finalize`),
  reopen: (pid: string) => request<Script>("POST", `${P(pid)}/script/reopen`),
  scriptText: (pid: string) => request<string>("GET", `${P(pid)}/script/text`),

  // Step 5
  startProduction: (pid: string) => request<Project>("POST", `${P(pid)}/production/start`),
  getProduction: (pid: string) => request<Production>("GET", `${P(pid)}/production`),
  // scene_ids를 주면 그 장면만, 없으면 전체 (영상은 '승인됐지만 영상이 없는 장면')
  generateImages: (pid: string, scene_ids?: string[]) => request("POST", `${P(pid)}/visual/images`, { scene_ids: scene_ids ?? null }),
  generateVideos: (pid: string, scene_ids?: string[]) => request("POST", `${P(pid)}/visual/videos`, { scene_ids: scene_ids ?? null }),
  approveAllImages: (pid: string) => request("POST", `${P(pid)}/visual/approve`),
  generateSound: (pid: string, scene_ids?: string[]) => request("POST", `${P(pid)}/sound/generate`, { scene_ids: scene_ids ?? null }),
  regenerateLine: (pid: string, sceneId: string, n: number) =>
    request<Production>("POST", `${P(pid)}/sound/scenes/${sceneId}/lines/${n}`),
  setTTSSettings: (pid: string, body: TTSSettings & { voice_id: string }) => request<Production>("PUT", `${P(pid)}/sound/settings`, body),
  previewTTS: (pid: string, body: TTSSettings & { voice_id: string }) =>
    request<{ url: string; text: string }>("POST", `${P(pid)}/sound/preview`, body),
  voicesMeta: () => request<VoicesMeta>("GET", "/api/voices/meta"),
  estimate: (pid: string) => request<Estimate>("GET", `${P(pid)}/production/estimate`),
  setVideoModel: (pid: string, video_model: string) => request<Production>("PUT", `${P(pid)}/visual/model`, { video_model }),
  listVoices: (gender = "", age = "", trait = "") =>
    request<TypecastVoice[]>("GET", `/api/voices?${new URLSearchParams({ gender, age, trait })}`),
  confirmProduction: (pid: string) => request<Project>("POST", `${P(pid)}/production/confirm`),

  // Step 6
  exportList: (pid: string) => request<ExportList>("GET", `${P(pid)}/export`),

  // 승인 게이트
  pendingGates: () => request<Gate[]>("GET", "/api/gates"),
  projectGates: (pid: string) => request<Gate[]>("GET", `${P(pid)}/gates`),
  resolveGate: (pid: string, gateId: string, action: "approve" | "revise", comment = "") =>
    request<{ result: string; kind: string }>("POST", `${P(pid)}/gates/${gateId}`, { action, comment }),
  previewFlow: (gateId: string) => request<string>("POST", `/api/gates/${gateId}/preview-flow`),
};

export const zipUrl = (pid: string, keys: string[] | null) =>
  `${P(pid)}/export/zip${keys ? `?items=${encodeURIComponent(keys.join(","))}` : ""}`;

export const productBundleUrl = (pid: string) => `${P(pid)}/product/bundle`;

export const dataUrl = (pid: string, ...parts: string[]) => `/data/projects/${pid}/${parts.join("/")}`;
