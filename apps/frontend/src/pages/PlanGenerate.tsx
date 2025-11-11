import { useEffect, useMemo, useState } from "react";
import RunPicker from "../components/RunPicker";
import { finalisePlan, getRun } from "../lib/api";
import type { PlanBundle } from "../types";
import StatPill from "../components/StatPill";

function Modal({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative z-10 w-[min(680px,95vw)] rounded-xl border border-slate-700 bg-slate-900 p-4 shadow-xl">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button
            className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600"
            onClick={onClose}
          >
            Close
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export default function PlanGenerate() {
  const [runId, setRunId] = useState<string | null>(null);
  const [run, setRun] = useState<any>(null);
  const [bundle, setBundle] = useState<PlanBundle | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [resetBusy, setResetBusy] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetCounts, setResetCounts] = useState<Record<string, number> | null>(null);
  const API = (import.meta as any).env?.VITE_API_URL ?? "http://127.0.0.1:8000";

  useEffect(() => {
    if (!runId) { setRun(null); return; }
    (async () => {
      try {
        const payload = await getRun(runId);            // { run, requirement, ... }
        const r = payload.run ?? payload;               // tolerate either shape
        const priority = payload.requirement?.priority ?? null; // only from requirement
        setRun({ ...r, priority });
      } catch {
        setRun(null);
      }
    })();
  }, [runId]);

  const stats = useMemo(() => {
  if (!bundle) return null;

  const epics   = bundle.epics?.length ?? 0;
  const stories = bundle.stories?.length ?? 0;
  const tasks   = (bundle.stories ?? []).reduce(
    (acc, s) => acc + (s.tasks?.length ?? 0),
    0
  );
  const notes   = bundle.design_notes?.length ?? 0;

    return {
      epics,
      stories,
      tasks,
      notes,
      hasPV: !!bundle.product_vision,
      hasTS: !!bundle.technical_solution,
    };
  }, [bundle]);

  async function runPlan() {
    if (!runId) return;
    setBusy(true);
    setMsg(null);
    const t0 = performance.now();
    try {
      // NEW: only generate the remainder using the stored PV/TS
      const b = await finalisePlan(runId);
      setBundle(b);
      const ms = Math.round(performance.now() - t0);
      setMsg(`Finalised (remainder generated) in ${ms}ms`);
    } catch (e: any) {
      const msg = String(e?.message ?? e);
      if (/vision\/solution not found/i.test(msg) || /404/.test(msg)) {
        setMsg(
          "This run doesn't have Product Vision / Technical Solution yet. Go to Manage Run → Generate first."
        );
      } else {
        setMsg(`Error: ${msg}`);
      }
    } finally {
      setBusy(false);
    }
  }

    async function resetPlan() {
    if (!runId) return;
    setResetBusy(true);
    setMsg(null);
    try {
      const res = await fetch(`${API}/runs/${runId}/plan`, { method: "DELETE" });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt || `HTTP ${res.status}`);
      }
      const data = await res.json(); // { ok, deleted: {epics:..}, kept:[...]}
      setResetCounts(data?.deleted ?? null);
      setResetOpen(true);
      setMsg("Plan reset: cleared epics/stories/tasks/design notes (kept vision/solution).");
      // clear any loaded bundle since we just wiped it
      setBundle(null);
    } catch (e: any) {
      setMsg(`Reset failed: ${e?.message ?? String(e)}`);
    } finally {
      setResetBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Generate Plan</h1>

    <div className="flex items-center gap-3">
      <RunPicker value={runId} onChange={setRunId} />
      <button
        className="px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50"
        disabled={!runId || busy}
        title="Create or Re-generate epics/stories/tasks for a Run"
        onClick={runPlan}
      >
        Generate / Re-Plan
      </button>
      <button
        className="px-4 py-2 rounded bg-amber-600 hover:bg-amber-500 disabled:opacity-50"
        disabled={!runId || busy || resetBusy}
        onClick={resetPlan}
        title="Clears epics/stories/tasks/design notes; keeps Product Vision & Technical Solution"
      >
        {resetBusy ? "Resetting…" : "Reset Plan"}
      </button>
    </div>

      {run && (
        <div className="rounded-xl border border-slate-700 bg-slate-900 p-4 text-sm">
          <div className="opacity-70 mb-1">Selected run</div>
          <div className="grid md:grid-cols-3 gap-2">
            <div><span className="opacity-60">ID: </span><span className="font-mono">{run.id}</span></div>
            <div><span className="opacity-60">Title: </span>{run.title ?? "(untitled)"}</div>
            <div><span className="opacity-60">Status: </span>{run.status ?? "-"}</div>
          </div>
        </div>
      )}

      {msg && <div className="text-sm">{msg}</div>}

      {stats && (
        <div className="flex gap-2 flex-wrap">
          <StatPill label="Epics" value={stats.epics} />
          <StatPill label="Stories" value={stats.stories} />
          <StatPill label="Tasks" value={stats.tasks} />
          <StatPill label="Design notes" value={stats.notes} />
          <StatPill label="Vision" value={stats.hasPV ? "✓" : "—"} />
          <StatPill label="Solution" value={stats.hasTS ? "✓" : "—"} />
        </div>
      )}

    <Modal
        open={resetOpen}
        title="Plan reset completed"
        onClose={() => setResetOpen(false)}
      >
        {resetCounts ? (
          <div>
            <div className="opacity-80 mb-2">
              The following artefacts were deleted for this run:
            </div>
            <table className="w-full text-sm border border-slate-800 rounded overflow-hidden">
              <thead className="bg-slate-950/50">
                <tr>
                  <th className="text-left p-2 border-b border-slate-800">Table</th>
                  <th className="text-right p-2 border-b border-slate-800">Deleted</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(resetCounts).map(([k, v]) => (
                  <tr key={k} className="odd:bg-slate-950/30">
                    <td className="p-2">{k}</td>
                    <td className="p-2 text-right tabular-nums">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="opacity-70 text-xs mt-3">
              Product Vision & Technical Solution were preserved.
            </div>
          </div>
        ) : (
          <div className="opacity-80">No counts available.</div>
        )}
      </Modal>
    </div>
  );
}
