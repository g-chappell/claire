// apps/frontend/src/pages/Retrospective.tsx
import { useEffect, useMemo, useState } from "react";
import { BASE, getPlan as loadPlan, patchFeedback, synthesizeAIFeedback, type Kind } from "../lib/api";

type RunLite = { id: string; title?: string };
type Epic = { id: string; title: string; description?: string; feedback_human?: string; feedback_ai?: string };
type Story = {
  id: string;
  epic_id?: string;
  title: string;
  description?: string;
  feedback_human?: string;
  feedback_ai?: string;
};
type Task = {
  id: string;
  story_id?: string;
  title: string;
  description?: string;
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

  // Filters
  const [selectedEpicId, setSelectedEpicId] = useState<string>("");
  const [selectedStoryIdFilter, setSelectedStoryIdFilter] = useState<string>("");

  // Artefact selection
  const [kind, setKind] = useState<Kind>("epic");
  const [selectedId, setSelectedId] = useState("");

  // Feedback editors
  const [human, setHuman] = useState("");
  const [ai, setAI] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  // Load runs
  useEffect(() => {
    (async () => {
      const r = await fetch(`${BASE}/runs`);
      const data = await r.json();
      setRuns(Array.isArray(data) ? data : []);
      if (Array.isArray(data) && data[0]?.id) setRunId(data[0].id);
    })();
  }, []);

  // Load plan bundle for run
  useEffect(() => {
    if (!runId) return;
    (async () => {
      try {
        const bundle = await loadPlan(runId);
        setEpics(bundle?.epics ?? []);
        setStories(bundle?.stories ?? []);
        const flatTasks =
          (bundle?.stories ?? []).flatMap((s: any) =>
            (s.tasks ?? []).map((t: any) => ({ ...t, story_id: s.id }))
          );
        setTasks(flatTasks);

        // Reset UI on run change
        setSelectedEpicId("");
        setSelectedStoryIdFilter("");
        setSelectedId("");
        setHuman("");
        setAI("");
        setMsg(null);
      } catch (e) {
        console.error("load plan failed", e);
        setEpics([]); setStories([]); setTasks([]);
      }
    })();
  }, [runId]);

  // ---------- FILTERED VIEWS ----------
  // Epics filtered (if epic filter set, show only that one)
  const epicsFiltered = useMemo(() => {
    if (!selectedEpicId) return epics;
    return epics.filter(e => e.id === selectedEpicId);
  }, [epics, selectedEpicId]);

  // Stories filtered by epic filter, then optional story filter
  const storiesByEpic = useMemo(() => {
    if (!selectedEpicId) return stories;
    return stories.filter(s => (s.epic_id || "") === selectedEpicId);
  }, [stories, selectedEpicId]);

  const storiesFiltered = useMemo(() => {
    if (!selectedStoryIdFilter) return storiesByEpic;
    return storiesByEpic.filter(s => s.id === selectedStoryIdFilter);
  }, [storiesByEpic, selectedStoryIdFilter]);

  // Tasks filtered by story filter, else by epic filter, else all
  const tasksByEpic = useMemo(() => {
    if (!selectedEpicId) return tasks;
    const allowedStoryIds = new Set(stories.filter(s => (s.epic_id || "") === selectedEpicId).map(s => s.id));
    return tasks.filter(t => t.story_id && allowedStoryIds.has(t.story_id));
  }, [tasks, stories, selectedEpicId]);

  const tasksFiltered = useMemo(() => {
    if (selectedStoryIdFilter) {
      return tasks.filter(t => t.story_id === selectedStoryIdFilter);
    }
    return tasksByEpic;
  }, [tasks, tasksByEpic, selectedStoryIdFilter]);

  // ---------- ARTEFACT CANDIDATES (RESPECT FILTERS FOR ALL TYPES) ----------
  const candidates = useMemo(() => {
    if (kind === "epic") {
      return epicsFiltered.map(x => ({ id: x.id, label: x.title, human: x.feedback_human, ai: x.feedback_ai }));
    }
    if (kind === "story") {
      return storiesFiltered.map(x => ({ id: x.id, label: x.title, human: x.feedback_human, ai: x.feedback_ai }));
    }
    return tasksFiltered.map(x => ({ id: x.id, label: x.title, human: x.feedback_human, ai: x.feedback_ai }));
  }, [kind, epicsFiltered, storiesFiltered, tasksFiltered]);

  // Selected artefact + context
  const selectedItem = useMemo(() => {
    if (!selectedId) return null;
    if (kind === "epic")  return epics.find(e => e.id === selectedId) || null;
    if (kind === "story") return stories.find(s => s.id === selectedId) || null;
    return tasks.find(t => t.id === selectedId) || null;
  }, [kind, selectedId, epics, stories, tasks]);

  const selectedLabel = useMemo(() => {
    const c = candidates.find(c => c.id === selectedId);
    return c?.label || "";
  }, [selectedId, candidates]);

  const selectedDescription = (selectedItem as any)?.description || "";

  // Reset feedback boxes when selection changes
  useEffect(() => {
    const chosen = candidates.find(c => c.id === selectedId);
    setHuman(chosen?.human || "");
    setAI(chosen?.ai || "");
  }, [selectedId, candidates]);

  // Counts
  const counts = useMemo(() => {
    const totals = {
      epics: epics.length,
      stories: stories.length,
      tasks: tasks.length,
    };
    const filtered = {
      epics: epicsFiltered.length,
      stories: storiesFiltered.length,
      tasks: tasksFiltered.length,
    };
    return { totals, filtered };
  }, [epics, stories, tasks, epicsFiltered, storiesFiltered, tasksFiltered]);

  // Actions
  async function saveHuman() {
    if (!runId || !selectedId) return;
    setBusy(true); setMsg(null);
    try {
      const out = await patchFeedback(runId, kind, selectedId, { human });
      setAI(out.ai || "");
      setMsg("Saved ✅");
    } catch (e: any) {
      setMsg(`Save failed: ${e?.message || e}`);
    } finally {
      setBusy(false);
    }
  }

  async function genAI() {
    if (!runId || !selectedId) return;
    setBusy(true); setMsg(null);
    try {
      const out = await synthesizeAIFeedback(runId, kind, selectedId, human || undefined);
      setAI(out.ai || "");
      setMsg(`AI feedback generated (${out.model}) ✅`);
    } catch (e: any) {
      setMsg(`AI failed: ${e?.message || e}`);
    } finally {
      setBusy(false);
    }
  }

  // ---------- RENDER ----------
  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4">
      {/* Header + totals */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Retrospective & Feedback</h1>
        <div className="text-sm text-slate-600 space-x-3">
          <span>Epics: {counts.totals.epics}</span>
          <span>Stories: {counts.totals.stories}</span>
          <span>Tasks: {counts.totals.tasks}</span>
        </div>
      </div>

      {/* Filters */}
      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-lg font-semibold">Filters</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {/* Run */}
          <div>
            <div className="mb-1 text-sm text-slate-700">Run</div>
            <select
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              value={runId}
              onChange={e => {
                setRunId(e.target.value);
              }}
            >
              {runs.map(r => <option key={r.id} value={r.id}>{r.id}</option>)}
            </select>
          </div>

          {/* Epic filter */}
          <div>
            <div className="mb-1 text-sm text-slate-700">
              Epic filter <span className="text-xs text-slate-400">(scopes stories & tasks)</span>
            </div>
            <select
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              value={selectedEpicId}
              onChange={e => {
                setSelectedEpicId(e.target.value);
                setSelectedStoryIdFilter("");
                setSelectedId("");
              }}
            >
              <option value="">All epics</option>
              {epics.map(e => (
                <option key={e.id} value={e.id}>{e.title}</option>
              ))}
            </select>
            <div className="mt-1 text-xs text-slate-500">
              Filtered — Epics: {counts.filtered.epics} • Stories: {counts.filtered.stories} • Tasks: {counts.filtered.tasks}
            </div>
          </div>

          {/* Story filter */}
          <div>
            <div className="mb-1 text-sm text-slate-700">
              Story filter <span className="text-xs text-slate-400">(scopes tasks; narrowed by epic if set)</span>
            </div>
            <select
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              value={selectedStoryIdFilter}
              onChange={e => {
                setSelectedStoryIdFilter(e.target.value);
                setSelectedId("");
              }}
            >
              <option value="">All stories{selectedEpicId ? " in selected epic" : ""}</option>
              {(selectedEpicId ? storiesByEpic : stories).map(s => (
                <option key={s.id} value={s.id}>{s.title}</option>
              ))}
            </select>
          </div>
        </div>
      </section>

      {/* Selection box (Type + Artefact) */}
      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-lg font-semibold">Select artefact</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {/* Artefact type */}
          <div>
            <div className="mb-1 text-sm text-slate-700">Artefact type</div>
            <select
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              value={kind}
              onChange={e => {
                setKind(e.target.value as Kind);
                setSelectedId("");
              }}
            >
              <option value="epic">Epic</option>
              <option value="story">Story</option>
              <option value="task">Task</option>
            </select>
          </div>

          {/* Artefact selector (fully respects filters) */}
          <div className="md:col-span-2">
            <div className="mb-1 text-sm text-slate-700">Artefact</div>
            <select
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              value={selectedId}
              onChange={e => setSelectedId(e.target.value)}
            >
              <option value="">—</option>
              {candidates.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
            </select>
            <div className="mt-1 text-xs text-slate-500">
              Showing {candidates.length} {kind}{candidates.length === 1 ? "" : "s"} (filters applied)
            </div>

            {/* Selected context panel */}
            {selectedId && (
              <div className="w-full mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
                <div className="mb-1 text-sm text-slate-700">Selected {kind} context</div>
                <div className="text-slate-900 font-semibold">{selectedLabel || "(untitled)"}</div>
                <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">
                  {selectedDescription || "No description provided for this artefact."}
                </p>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Feedback editors */}
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
            <div className="mt-2 flex gap-2">
              <button
                onClick={saveHuman}
                disabled={!runId || !selectedId || busy}
                className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-1"
              >
                Save human feedback
              </button>
              <button
                onClick={genAI}
                disabled={!runId || !selectedId || busy}
                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 hover:border-slate-400 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-slate-300 focus:ring-offset-1"
              >
                Generate AI feedback
              </button>
            </div>
          </div>
          <div>
            <div className="mb-1 text-sm font-semibold">AI feedback</div>
            <textarea
              className="h-48 w-full rounded-md border border-slate-300 bg-white p-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              value={ai}
              onChange={e => setAI(e.target.value)}
              placeholder="AI synthesis will appear here…"
            />
            <div className="mt-2">
              <button
                onClick={() => patchFeedback(runId, kind, selectedId, { ai })}
                disabled={!runId || !selectedId || busy}
                className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-1"
              >
                Save AI feedback
              </button>
            </div>
          </div>
        </div>
        {msg && <div className="mt-3 text-sm text-slate-600">{msg}</div>}
      </section>
    </div>
  );
}
