import { useEffect, useMemo, useState } from "react";
import RunPicker from "../components/RunPicker";
import { generatePlan, getRun } from "../lib/api";
import type { PlanBundle } from "../types";
import StatPill from "../components/StatPill";

export default function PlanGenerate() {
  const [runId, setRunId] = useState<string | null>(null);
  const [run, setRun] = useState<any>(null);
  const [bundle, setBundle] = useState<PlanBundle | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!runId) { setRun(null); return; }
    (async () => {
      try { setRun(await getRun(runId)); } catch { setRun(null); }
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

  async function runPlan(force = true) {
    if (!runId) return;
    setBusy(true); setMsg(null);
    const t0 = performance.now();
    try {
      const b = await generatePlan(runId, force);
      setBundle(b);
      const ms = Math.round(performance.now() - t0);
      setMsg(`Plan generated in ${ms}ms`);
    } catch (e:any) {
      setMsg(`Error: ${e.message ?? e}`);
    } finally { setBusy(false); }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Generate Plan</h1>

      <div className="flex items-center gap-3">
        <RunPicker value={runId} onChange={setRunId} />
        <button
          className="px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50"
          disabled={!runId || busy}
          onClick={() => runPlan(true)}
        >
          Generate / Re-Plan
        </button>
      </div>

      {run && (
        <div className="rounded-xl border border-slate-700 bg-slate-900 p-4 text-sm">
          <div className="opacity-70 mb-1">Selected run</div>
          <div className="grid md:grid-cols-3 gap-2">
            <div><span className="opacity-60">ID: </span><span className="font-mono">{run.id}</span></div>
            <div><span className="opacity-60">Title: </span>{run.title ?? "(untitled)"}</div>
            <div><span className="opacity-60">Priority: </span>{run.priority ?? "-"}</div>
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
    </div>
  );
}
