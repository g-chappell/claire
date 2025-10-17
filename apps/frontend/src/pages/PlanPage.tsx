// src/PlanPage.tsx
import { useEffect, useMemo, useState } from "react";

// add this helper
async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const base = (import.meta as any).env?.VITE_API_URL ?? "";
  const res = await fetch(`${base}${path}`, {
    // set JSON header only if you pass a body; preserve any custom headers
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}


type Acceptance = { story_id: string; gherkin: string };
type Task = { id: string; story_id: string; title: string; order: number; status: string };
type Story = {
  id: string; epic_id: string; title: string; description: string;
  priority_rank: number; acceptance: Acceptance[]; tests: string[]; tasks: Task[];
};
type Epic = { id: string; title: string; description: string; priority_rank: number };
type ProductVision = { id: string; goals: string[]; personas: string[]; features: string[] };
type TechnicalSolution = { id: string; stack: string[]; modules: string[]; interfaces: Record<string,string>; decisions: string[] };
type PlanBundle = { product_vision: ProductVision; technical_solution: TechnicalSolution; epics: Epic[]; stories: Story[]; design_notes?: any[] };

type RunSummary = { id: string; title?: string; status?: string; created_at?: string };

export default function PlanPage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runId, setRunId] = useState<string>("");
  const [bundle, setBundle] = useState<PlanBundle | null>(null);
  const [creating, setCreating] = useState(false);
  const [planning, setPlanning] = useState(false);

  const [title, setTitle] = useState("Run M1.2 (UI)");
  const [reqTitle, setReqTitle] = useState("As a user, I can see health");
  const [reqDesc, setReqDesc] = useState("Expose /health returning {status: ok}");

  async function refreshRuns() {
    const list = await json<RunSummary[]>("/runs");
    setRuns(list);
    if (!runId && list.length) setRunId(list[0].id);
  }

  async function createRun() {
    setCreating(true);
    try {
      const res = await json<{ run_id: string }>("/runs", {
        method: "POST",
        body: JSON.stringify({
          title,
          requirement_title: reqTitle,
          requirement_description: reqDesc,
          constraints: [],
          priority: "Should",
          non_functionals: [],
        }),
      });
      setRunId(res.run_id);
      await refreshRuns();
    } finally {
      setCreating(false);
    }
  }

  async function getPlan() {
    if (!runId) return;
    const data = await json<PlanBundle>(`/runs/${runId}/plan`);
    setBundle(data);
  }

  async function planNow() {
    if (!runId) return;
    setPlanning(true);
    try {
      const data = await json<PlanBundle>(`/runs/${runId}/plan?force=true`, { method: "POST" });
      setBundle(data);
    } finally {
      setPlanning(false);
    }
  }

  useEffect(() => { refreshRuns(); }, []);

  const storiesByEpic = useMemo(() => {
    const map: Record<string, Story[]> = {};
    (bundle?.stories ?? []).forEach((s) => {
      (map[s.epic_id] ||= []).push(s);
    });
    Object.values(map).forEach(list => list.sort((a,b) => a.priority_rank - b.priority_rank));
    return map;
  }, [bundle]);

  return (
    <main className="p-6 space-y-6">
      <header className="flex items-end gap-4 flex-wrap">
        <div>
          <h2 className="text-2xl font-semibold">Plan</h2>
          <p className="opacity-70 text-sm">Create a run, generate a plan, and inspect artifacts.</p>
        </div>

        <div className="ml-auto flex items-center gap-3">
          <button
            onClick={refreshRuns}
            className="px-3 py-2 rounded-lg bg-slate-700 hover:bg-slate-600"
            title="Refresh runs"
          >
            Refresh
          </button>
          <select
            value={runId}
            onChange={(e) => setRunId(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2"
          >
            <option value="">Select run…</option>
            {runs.map(r => (
              <option key={r.id} value={r.id}>
                {r.title ?? "(untitled)"} — {r.id.slice(0,8)}
              </option>
            ))}
          </select>
          <button
            onClick={getPlan}
            disabled={!runId}
            className="px-3 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 disabled:opacity-50"
          >
            Load Plan
          </button>
          <button
            onClick={planNow}
            disabled={!runId || planning}
            className="px-3 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50"
          >
            {planning ? "Planning…" : "Generate Plan"}
          </button>
        </div>
      </header>

      {/* Create Run */}
      <section className="grid gap-3 bg-slate-800 border border-slate-700 rounded-xl p-4">
        <div className="grid sm:grid-cols-3 gap-3">
          <label className="grid gap-1">
            <span className="text-sm opacity-80">Run title</span>
            <input value={title} onChange={e=>setTitle(e.target.value)}
              className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2"/>
          </label>
          <label className="grid gap-1 sm:col-span-2">
            <span className="text-sm opacity-80">Requirement title</span>
            <input value={reqTitle} onChange={e=>setReqTitle(e.target.value)}
              className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2"/>
          </label>
        </div>
        <label className="grid gap-1">
          <span className="text-sm opacity-80">Requirement description</span>
          <textarea value={reqDesc} onChange={e=>setReqDesc(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 h-24"/>
        </label>
        <div>
          <button
            onClick={createRun}
            disabled={creating}
            className="px-3 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50"
          >
            {creating ? "Creating…" : "Create Run"}
          </button>
        </div>
      </section>

      {/* Plan Bundle */}
      {!!bundle && (
        <section className="grid gap-6">
          {/* Vision + Solution */}
          <div className="grid md:grid-cols-2 gap-6">
            <Card title="Product Vision">
              <L list={bundle.product_vision.goals} label="Goals" />
              <L list={bundle.product_vision.personas} label="Personas" />
              <L list={bundle.product_vision.features} label="Features" />
            </Card>
            <Card title="Technical Solution">
              <L list={bundle.technical_solution.stack} label="Stack" />
              <L list={bundle.technical_solution.modules} label="Modules" />
              <KV map={bundle.technical_solution.interfaces} label="Interfaces" />
              <L list={bundle.technical_solution.decisions} label="Decisions" />
            </Card>
          </div>

          {/* Epics & Stories */}
          <div className="grid gap-3">
            <h3 className="text-lg font-semibold">Backlog</h3>
            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
              {bundle.epics.sort((a,b)=>a.priority_rank-b.priority_rank).map(epic => (
                <div key={epic.id} className="bg-slate-800 border border-slate-700 rounded-xl p-4">
                  <div className="flex items-baseline justify-between">
                    <h4 className="font-semibold">{epic.title}</h4>
                    <span className="text-xs opacity-70">P{epic.priority_rank}</span>
                  </div>
                  {!!epic.description && (
                    <p className="text-sm opacity-80 mt-1">{epic.description}</p>
                  )}
                  <div className="mt-3 space-y-3">
                    {(storiesByEpic[epic.id] ?? []).map(story => (
                      <div key={story.id} className="bg-slate-900 border border-slate-800 rounded-lg p-3">
                        <div className="flex items-baseline justify-between">
                          <div className="font-medium">{story.title}</div>
                          <span className="text-xs opacity-70">P{story.priority_rank}</span>
                        </div>
                        {!!story.description && (
                          <p className="text-sm opacity-80 mt-1">{story.description}</p>
                        )}

                        {/* Tasks */}
                        {(story.tasks?.length ?? 0) > 0 && (
                          <div className="mt-2">
                            <div className="text-xs uppercase opacity-70 mb-1">Tasks</div>
                            <ul className="text-sm list-disc pl-5 space-y-1">
                              {story.tasks.sort((a,b)=>a.order-b.order).map(t => (
                                <li key={t.id}>{t.title}</li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {/* AC */}
                        {(story.acceptance?.length ?? 0) > 0 && (
                          <details className="mt-2">
                            <summary className="cursor-pointer text-sm opacity-90">Acceptance (Gherkin)</summary>
                            <div className="mt-1 text-xs whitespace-pre-wrap opacity-90">
                              {story.acceptance.map((a,i)=>(
                                <div key={i} className="mb-2">{a.gherkin}</div>
                              ))}
                            </div>
                          </details>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}
    </main>
  );
}

function Card({ title, children }: { title: string; children: any }) {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
      <div className="text-lg font-semibold mb-2">{title}</div>
      {children}
    </div>
  );
}
function L({ list, label }: { list: string[]; label: string }) {
  if (!list?.length) return null;
  return (
    <div className="mb-3">
      <div className="text-xs uppercase opacity-70 mb-1">{label}</div>
      <ul className="list-disc pl-5 space-y-1 text-sm">
        {list.map((x,i)=><li key={i}>{x}</li>)}
      </ul>
    </div>
  );
}
function KV({ map, label }: { map: Record<string,string>; label: string }) {
  const keys = Object.keys(map ?? {});
  if (!keys.length) return null;
  return (
    <div className="mb-3">
      <div className="text-xs uppercase opacity-70 mb-1">{label}</div>
      <ul className="space-y-1 text-sm">
        {keys.map(k => (
          <li key={k}><span className="opacity-70">{k}</span>: {map[k]}</li>
        ))}
      </ul>
    </div>
  );
}
