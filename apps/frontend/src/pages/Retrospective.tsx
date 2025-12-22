// apps/frontend/src/pages/Retrospective.tsx
import { useEffect, useState } from "react";
import { BASE, getPlan as loadPlan, getVisionSolution, patchPlanFeedback, synthesizePlanAIFeedback, commitSelectedFeedbackExemplar, getPlanFeedback, type PlanArtifactKind } from "../lib/api";

type RunLite = { id: string; title?: string };
type Epic = {
  id: string;
  title: string;
  description?: string;
  priority_rank?: number;
  feedback_human?: string;
  feedback_ai?: string;
};

type Story = {
  id: string;
  epic_id?: string;
  title: string;
  description?: string;
  priority_rank?: number;
  feedback_human?: string;
  feedback_ai?: string;
};

type Task = {
  id: string;
  story_id?: string;
  title: string;
  description?: string;
  order?: number;
  feedback_human?: string;
  feedback_ai?: string;
};

export default function RetrospectivePage() {
  // Data
  const [runs, setRuns] = useState<RunLite[]>([]);
  const [runId, setRunId] = useState("");

  const [epics, setEpics] = useState<Epic[]>([]);
  const [stories, setStories] = useState<Story[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);

  // PV/TS (stage-gate)
  const [visionSolution, setVisionSolution] = useState<any | null>(null);

  // Artefact selection
  const [kind, setKind] = useState<PlanArtifactKind>("product_vision");

  // Story selector (required for story_tasks)
  const [selectedStoryId, setSelectedStoryId] = useState<string>("");

  // Context (what the SM sees + what you ingest as exemplar)
  const [contextText, setContextText] = useState<string>("");

  // Feedback editors (run-level feedback)
  const [human, setHuman] = useState("");
  const [ai, setAI] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  // ---------------- Load runs ----------------
  useEffect(() => {
    (async () => {
      const r = await fetch(`${BASE}/runs`);
      const data = await r.json();
      setRuns(Array.isArray(data) ? data : []);
      if (Array.isArray(data) && data[0]?.id) setRunId(data[0].id);
    })();
  }, []);

  // ---------------- Load plan + PV/TS for run ----------------
  useEffect(() => {
    if (!runId) return;
    (async () => {
      try {
        // Plan bundle (for RA plan + story_tasks context generation)
        const bundle = await loadPlan(runId);
        const nextEpics = bundle?.epics ?? [];
        const nextStories = bundle?.stories ?? [];

        setEpics(nextEpics);
        setStories(nextStories);

        // Default story selection for story_tasks
        setSelectedStoryId(nextStories[0]?.id ?? "");

        const flatTasks =
          (bundle?.stories ?? []).flatMap((s: any) =>
            (s.tasks ?? []).map((t: any) => ({ ...t, story_id: s.id }))
          );
        setTasks(flatTasks);

        // PV/TS (for PV/TS context)
        try {
          const vs = await getVisionSolution(runId);
          setVisionSolution(vs);
        } catch {
          setVisionSolution(null);
        }

        // Reset feedback UI when run changes
        setMsg(null);
      } catch (e) {
        console.error("load plan failed", e);
        setEpics([]);
        setStories([]);
        setTasks([]);
        setVisionSolution(null);
      }
    })();
  }, [runId]);

  useEffect(() => {
  if (!runId) return;

  // story_tasks requires story_id
  if (kind === "story_tasks" && !selectedStoryId) {
    setHuman("");
    setAI("");
    return;
  }

  (async () => {
    try {
      const out = await getPlanFeedback(runId, kind, {
        story_id: kind === "story_tasks" ? selectedStoryId : undefined,
      });
      setHuman(out?.human ?? "");
      setAI(out?.ai ?? "");
    } catch (e) {
      console.error("getPlanFeedback failed", e);
      // don't wipe fields on transient error; optional:
      // setHuman(""); setAI("");
    }
  })();
}, [runId, kind, selectedStoryId]);

  // ---------------- Helpers: build run-level context ----------------
  function buildProductVisionContext() {
    const pv = visionSolution?.product_vision ?? null;
    return pv ? JSON.stringify(pv, null, 2) : "(No Product Vision found for this run)";
  }

  function buildTechnicalSolutionContext() {
    const ts = visionSolution?.technical_solution ?? null;
    return ts ? JSON.stringify(ts, null, 2) : "(No Technical Solution found for this run)";
  }

  function buildRaPlanContext() {
    const lines: string[] = [];
    lines.push("RA PLAN (EPICS & STORIES)");
    lines.push("");

    const eps = [...epics].sort((a: any, b: any) => (a.priority_rank ?? 0) - (b.priority_rank ?? 0));
    const sts = [...stories].sort((a: any, b: any) => (a.priority_rank ?? 0) - (b.priority_rank ?? 0));

    for (const e of eps) {
      lines.push(`EPIC: ${e.title || "(untitled)"}`);
      if (e.description) lines.push(e.description);
      lines.push("");

      const eStories = sts.filter(s => (s.epic_id || "") === e.id);
      if (!eStories.length) {
        lines.push("  (no stories)");
        lines.push("");
        continue;
      }

      lines.push("  STORIES:");
      for (const s of eStories) {
        lines.push(`  - ${s.title || "(untitled story)"}`);
        if (s.description) lines.push(`    ${s.description}`);
      }
      lines.push("");
    }

    return lines.join("\n");
  }

  function buildStoryTasksContext(storyId: string) {
    if (!storyId) return "(Select a story to view Story Tasks context)";

    const s = stories.find(x => x.id === storyId);
    if (!s) return "(Story not found for this run)";

    const lines: string[] = [];
    lines.push("STORY TASKS (SELECTED STORY)");
    lines.push("");
    lines.push(`STORY: ${s.title || "(untitled story)"}`);
    if (s.description) lines.push(s.description);
    lines.push("");

    const sTasks = tasks
      .filter(t => t.story_id === s.id)
      .sort((a: any, b: any) => ((a as any).order ?? 0) - ((b as any).order ?? 0));

    if (!sTasks.length) {
      lines.push("  TASKS: (none)");
      lines.push("");
      return lines.join("\n");
    }

    lines.push("  TASKS:");
    for (const t of sTasks) {
      lines.push(`  - ${t.title || "(untitled task)"}`);
      if (t.description) lines.push(`    ${t.description}`);
    }
    lines.push("");

    return lines.join("\n");
  }

  // Update context when kind changes OR data changes
  useEffect(() => {
    if (kind === "product_vision") setContextText(buildProductVisionContext());
    else if (kind === "technical_solution") setContextText(buildTechnicalSolutionContext());
    else if (kind === "ra_plan") setContextText(buildRaPlanContext());
    else setContextText(buildStoryTasksContext(selectedStoryId));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, visionSolution, epics, stories, tasks, selectedStoryId]);

  // ---------------- Actions ----------------
  async function saveFeedback() {
    if (!runId) return;
    setBusy(true); setMsg(null);
    try {
      // Plan-level feedback: run_id + artefact_type only (no IDs)
            const out = await patchPlanFeedback(runId, kind, {
        human,
        ai,
        story_id: kind === "story_tasks" ? selectedStoryId : undefined,
      });
      setHuman(out?.human ?? human);
      setAI(out?.ai ?? ai);
      setMsg("Saved ✅");
    } catch (e: any) {
      setMsg(`Save failed: ${e?.message || e}`);
    } finally {
      setBusy(false);
    }
  }

  async function genAI() {
    if (!runId) return;
    setBusy(true); setMsg(null);
    try {
      const out = await synthesizePlanAIFeedback(runId, kind, {
        human_override: human || undefined,
        story_id: kind === "story_tasks" ? selectedStoryId : undefined,
      });
      setAI(out?.ai || "");
      setMsg(`AI feedback generated (${out?.model || "model"}) ✅`);
    } catch (e: any) {
      setMsg(`AI failed: ${e?.message || e}`);
    } finally {
      setBusy(false);
    }
  }

async function commitSelectedAsExemplar() {
  if (!runId) return;
  setBusy(true); setMsg(null);

  try {
    const out = await commitSelectedFeedbackExemplar(
      runId,
      kind,
      kind === "story_tasks" ? selectedStoryId : undefined
    );

    const del = typeof out.deleted === "number" ? out.deleted : 0;
    setMsg(`Committed exemplar (${out.added}, deleted ${del}) ✅`);
  } catch (e: any) {
    setMsg(`Commit failed: ${e?.message || e}`);
  } finally {
    setBusy(false);
  }
}

  // ---------------- Render ----------------
  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Retrospective & Feedback</h1>
      </div>

      {/* Run */}
      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-lg font-semibold">Run</h2>
        <select
          className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
          value={runId}
          onChange={e => setRunId(e.target.value)}
        >
          {runs.map(r => <option key={r.id} value={r.id}>{r.id}</option>)}
        </select>
      </section>

      {/* Artefact type */}
      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-lg font-semibold">Artefact type</h2>
        <select
          className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
          value={kind}
          onChange={e => setKind(e.target.value as PlanArtifactKind)}
        >
          <option value="product_vision">Product Vision</option>
          <option value="technical_solution">Technical Solution</option>
          <option value="ra_plan">RA Plan (Epics & Stories)</option>
          <option value="story_tasks">Story Tasks (all stories)</option>
        </select>
                {kind === "story_tasks" && (
          <div className="mt-3">
            <div className="mb-1 text-sm text-slate-700">Story (required for Story Tasks)</div>
            <select
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              value={selectedStoryId}
              onChange={e => setSelectedStoryId(e.target.value)}
            >
              {stories.map(s => (
                <option key={s.id} value={s.id}>
                  {s.title || s.id}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
          <div className="mb-1 text-sm text-slate-700">Context (read-only)</div>
          <pre className="whitespace-pre-wrap text-xs text-slate-800">{contextText}</pre>
        </div>
      </section>

      {/* Feedback */}
      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <div className="mb-1 text-sm font-semibold">Human feedback</div>
            <textarea
              className="h-48 w-full rounded-md border border-slate-300 bg-white p-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              value={human}
              onChange={e => setHuman(e.target.value)}
              placeholder="Add actionable critique, constraints, risks, priorities…"
            />
          </div>
          <div>
            <div className="mb-1 text-sm font-semibold">AI feedback</div>
            <textarea
              className="h-48 w-full rounded-md border border-slate-300 bg-white p-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              value={ai}
              onChange={e => setAI(e.target.value)}
              placeholder="AI synthesis will appear here…"
            />
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <button
            onClick={saveFeedback}
            disabled={!runId || busy || (kind === "story_tasks" && !selectedStoryId)}
            className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-1"
          >
            Save Human feedback
          </button>

          <button
            onClick={genAI}
            disabled={!runId || busy || (kind === "story_tasks" && !selectedStoryId)}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 hover:border-slate-400 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-slate-300 focus:ring-offset-1"
          >
            Generate & Save AI feedback
          </button>

          <button
            onClick={commitSelectedAsExemplar}
            disabled={!runId || busy || (kind === "story_tasks" && !selectedStoryId)}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 hover:border-slate-400 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-slate-300 focus:ring-offset-1"
            title="Push an exemplar to the RAG store for this artefact type"
          >
            Commit exemplar to RAG store
          </button>
        </div>

        {msg && <div className="mt-3 text-sm text-slate-600">{msg}</div>}
      </section>
    </div>
  );
}
