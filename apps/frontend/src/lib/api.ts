import type {
  // runs
  RunCreate,
  RunSummary,
  RunDetail,
  // plan bundle + subtypes
  PlanBundle,
  // ProductVision,
  // TechnicalSolution,
  // AcceptanceCriteria,
  // Task,
  // Story,
  // Epic,
  // DesignNote,
  // stage-gate bundle
  VisionSolution,
} from "../types"

export const BASE =
  import.meta.env.VITE_API_BASE ||
  import.meta.env.VITE_API_URL ||
  import.meta.env.NEXT_PUBLIC_API_URL ||
  (location.hostname.endsWith("blacksail.dev")
    ? "https://api.blacksail.dev"
    : "http://127.0.0.1:8000");

  // Resolve the base URL without changing your existing BASE/API_BASE logic.
// We intentionally don't "declare" types to avoid collisions if you already export them.
// @ts-ignore — provided by your existing block above
const BASE_URL: string =
  // @ts-ignore
  (typeof API_BASE !== "undefined" ? API_BASE :
  // @ts-ignore
  (typeof BASE !== "undefined" ? BASE : ""));

  // ---------------- Minimal JSON helper ----------------
async function req<T>(
  path: string,
  init?: RequestInit & { json?: unknown }
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: init?.method ?? "GET",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    body: init?.json !== undefined ? JSON.stringify(init.json) : init?.body,
  });

  if (!res.ok) {
    try {
      const j = await res.json();
      throw new Error(j?.detail ?? JSON.stringify(j));
    } catch {
      throw new Error(`${res.status} ${res.statusText}`);
    }
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

// ---------------- Runs ----------------
export function listRuns(): Promise<RunSummary[]> {
  return req<RunSummary[]>("/runs");
}

export function getRun(runId: string): Promise<RunDetail> {
  return req<RunDetail>(`/runs/${encodeURIComponent(runId)}`);
}

export function createRun(body: RunCreate): Promise<RunDetail> {
  return req<RunDetail>("/runs", { method: "POST", json: body });
}

export function deleteRun(
  runId: string
): Promise<{ ok: boolean; deleted?: Record<string, number> }> {
  return req<{ ok: boolean; deleted?: Record<string, number> }>(
    `/runs/${encodeURIComponent(runId)}`, 
    { method: "DELETE" }
  );
}

// ---------------- Plan (one-shot, back-compat) ----------------
export function getPlan(runId: string): Promise<PlanBundle> {
  return req<PlanBundle>(`/runs/${encodeURIComponent(runId)}/plan`);
}

export function generatePlan(
  runId: string,
  opts?: { force?: boolean }
): Promise<PlanBundle> {
  const q = opts?.force ? "?force=true" : "";
  return req<PlanBundle>(`/runs/${encodeURIComponent(runId)}/plan${q}`, {
    method: "POST",
  });
}

// ---------------- Stage-gate: PV/TS ----------------
export function getVisionSolution(runId: string): Promise<VisionSolution> {
  return req<VisionSolution>(
    `/runs/${encodeURIComponent(runId)}/plan/vision-solution`
  );
}

export function generateVisionSolution(runId: string): Promise<VisionSolution> {
  return req<VisionSolution>(
    `/runs/${encodeURIComponent(runId)}/plan/vision-solution`,
    { method: "POST" }
  );
}

export function updateVisionSolution(
  runId: string,
  body: Partial<VisionSolution>
): Promise<VisionSolution> {
  return req<VisionSolution>(
    `/runs/${encodeURIComponent(runId)}/plan/vision-solution`,
    { method: "PUT", json: body }
  );
}

// ---------------- Stage 2: Finalise (generate remainder only) ----------------
export function finalisePlan(
  runId: string,
  body?: Partial<VisionSolution>
): Promise<PlanBundle> {
  return req<PlanBundle>(
    `/runs/${encodeURIComponent(runId)}/plan/finalise`,
    { method: "POST", json: body ?? {} }
  );
}

export async function commitMemory(payload: {
  run_id: string;
  artifacts: {
    type: "requirement" | "product_vision" | "technical_solution";
    title?: string;
    text: string;
  }[];
}) {
  const res = await fetch(`${import.meta.env.VITE_API_URL}/memory/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateGateStatus(runId: string, status: "approved"|"draft"|"rejected") {
  const res = await fetch(`${import.meta.env.VITE_API_URL}/runs/${runId}/gate`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ vision_solution_status: status }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ run_id: string; vision_solution_status: string }>;
}

export async function getGateStatus(runId: string) {
  const res = await fetch(`${import.meta.env.VITE_API_URL}/runs/${runId}/gate`);
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ run_id: string; vision_solution_status: string | null }>;
}

// --- PLAN: fetch a plan bundle for a run ---
// Tries /plan/runs/{id}. If that 404s, falls back to /runs/{id}.
export async function fetchPlanBundle(runId: string): Promise<{
  epics: Array<{ title: string; description?: string }>;
  stories: Array<{ id?: string; story_id?: string; epic_title: string; title: string; description?: string }>;
  tasks: Array<{ id?: string; task_id?: string; story_id?: string; title?: string; description?: string; order?: number }>;
}> {
  const base = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  const tryFetch = async (url: string) => {
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  };

  try {
    // Primary: dedicated planning endpoint
    const data = await tryFetch(`${base}/plan/runs/${encodeURIComponent(runId)}`);
    return normalizePlanShape(data);
  } catch (e: any) {
    // Fallback: some backends return epics/stories/tasks on /runs/{id}
    const fallback = await tryFetch(`${base}/runs/${encodeURIComponent(runId)}`);
    return normalizePlanShape(fallback);
  }

  // ---- helpers ----
  function normalizePlanShape(src: any) {
    // Accepts { epics, stories, tasks } or places where those live under nested keys.
    const epics = coerceArray(src?.epics ?? src?.plan?.epics ?? []);
    const stories = coerceArray(src?.stories ?? src?.plan?.stories ?? []);
    // tasks may be flat OR nested under each story
    let tasks = coerceArray(src?.tasks ?? src?.plan?.tasks ?? []);
    if (!tasks.length && stories.length) {
      // If tasks are nested under stories
      const flat: any[] = [];
      for (const s of stories) {
        const sid = (s.id || s.story_id || "").toString();
        const sTasks = coerceArray(s?.tasks ?? s?.plan_tasks ?? []);
        for (const t of sTasks) {
          flat.push({ ...t, story_id: t.story_id ?? sid });
        }
      }
      tasks = flat;
    }
    return { epics, stories, tasks };
  }

  function coerceArray(v: any) {
    return Array.isArray(v) ? v : v ? [v] : [];
  }
}

export type Kind = "epic" | "story" | "task";

export async function patchFeedback(runId: string, kind: Kind, id: string, payload: { human?: string; ai?: string }) {
  const res = await fetch(`${BASE}/runs/${runId}/${kind}/${id}/feedback`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`patchFeedback failed: ${res.status}`);
  return res.json();
}

export async function synthesizeAIFeedback(runId: string, kind: Kind, id: string, humanOverride?: string) {
  const res = await fetch(`${BASE}/runs/${runId}/${kind}/${id}/feedback/ai`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(humanOverride ? { human_override: humanOverride } : {}),
  });
  if (!res.ok) throw new Error(`synthesizeAIFeedback failed: ${res.status}`);
  return res.json();
}