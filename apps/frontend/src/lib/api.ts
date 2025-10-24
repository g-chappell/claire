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

const BASE =
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
