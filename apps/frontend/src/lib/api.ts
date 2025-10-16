import type { RunCreate, RunSummary, PlanBundle } from "../types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

const noStore: RequestInit = { cache: "no-store", headers: { "cache-control": "no-store" } };

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<T>;
}

export async function createRun(data: RunCreate): Promise<{ run_id: string }> {
  const res = await fetch(`${BASE}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return asJson(res);
}

export async function listRuns(): Promise<RunSummary[]> {
  // defeat any intermediary caching
  const res = await fetch(`${BASE}/runs?t=${Date.now()}`, {
    method: "GET",
    headers: { "Cache-Control": "no-cache" },
  });
  if (res.status === 404 || res.status === 405) return [];
  return asJson(res);
}

export async function getRun(runId: string): Promise<any> {
  const res = await fetch(`${BASE}/runs/${runId}`, noStore);
  return asJson(res);
}

export async function getLastRunId(): Promise<string | null> {
  const res = await fetch(`${BASE}/runs/last?t=${Date.now()}`, {
    headers: { "Cache-Control": "no-cache" },
  });
  if (res.ok) {
    const j = await res.json();
    return j.run_id ?? null;
  }
  const runs = await listRuns();
  return runs[0]?.id ?? null;
}

export async function deleteRun(runId: string): Promise<{ ok: boolean; deleted?: any; stubbed?: boolean }> {
  const res = await fetch(`${BASE}/runs/${runId}`, { method: "DELETE" });
  if (res.status === 404 || res.status === 405) return { ok: true, stubbed: true };
  const body = await res.json().catch(() => ({}));
  return { ok: res.ok, deleted: body.deleted };
}

export async function generatePlan(runId: string, force = true): Promise<PlanBundle> {
  const res = await fetch(`${BASE}/runs/${runId}/plan?force=${force ? "true" : "false"}`, { method: "POST" });
  return asJson(res);
}

export async function loadPlan(runId: string): Promise<PlanBundle> {
  const res = await fetch(`${BASE}/runs/${runId}/plan`, noStore);
  return asJson(res);
}