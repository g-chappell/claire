// src/pages/ImplementCode.tsx
import React, { useEffect, useMemo, useState } from "react";
import { listRuns as apiListRuns, getPlan as loadPlan } from "../lib/api"; // ← same helpers PlanView uses

// Loosely-typed to tolerate older bundles
type RunLite = { id: string; created_at?: string; title?: string };

type Epic = {
  id?: string;
  title: string;
  description?: string;
};

type Task = {
  id?: string;
  task_id?: string;
  story_id?: string;
  title?: string;
  description?: string;
  order?: number;
};

type Story = {
  id?: string;
  story_id?: string;
  epic_id?: string;
  epic_title?: string; // some older responses included this
  title: string;
  description?: string;
  priority_rank?: number;
  tasks?: Task[];
};

type PlanBundle = {
  epics?: Epic[];
  stories?: Story[];
  // Some backends *also* return a flat tasks[]; we won’t rely on it.
};

type ImplementResult = {
  run_id: string;
  story_id?: string;
  results?: Array<{
    task_id?: string;
    ok?: boolean;
    error?: string;
    message?: string;
    file_changes?: any;
    tool_calls?: any[];
  }>;
};

const API =
  import.meta.env.VITE_API_URL?.replace(/\/+$/, "") ||
  import.meta.env.NEXT_PUBLIC_API_URL?.replace(/\/+$/, "") ||
  "http://127.0.0.1:8000";

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full border border-slate-700 bg-slate-800/60 px-2 py-0.5 text-xs text-slate-200">
      {children}
    </span>
  );
}

function Section({
  title,
  right,
  children,
}: {
  title: string;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-slate-700 bg-slate-900 p-4">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-lg font-semibold">{title}</h2>
        {right ? <div className="flex items-center gap-2">{right}</div> : null}
      </div>
      {children}
    </section>
  );
}

export default function ImplementCodePage() {
  // Runs & selection
  const [runs, setRuns] = useState<RunLite[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>("");

  // PLAN DATA (from /runs/{id}/plan)
  const [epics, setEpics] = useState<Epic[]>([]);
  const [stories, setStories] = useState<Story[]>([]);
  const [flatTasks, setFlatTasks] = useState<Task[]>([]); // derived from stories[].tasks

  // Tools & execution state
  const [tools, setTools] = useState<string[]>([]);
  const [loadingTools, setLoadingTools] = useState(false);
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const [lastResult, setLastResult] = useState<ImplementResult | null>(null);

  // UI selections
  const [selectedEpic, setSelectedEpic] = useState<string>("");
  const [selectedStoryId, setSelectedStoryId] = useState<string>("");

  // Front-end progress memory
  const [progressByStory, setProgressByStory] = useState<
    Record<string, { total: number; ok: number; errors: number }>
  >({});

  // --- Load runs (same source as RunPicker/PlanView)
  useEffect(() => {
    (async () => {
      try {
        const list = await apiListRuns();
        setRuns(list ?? []);
        if (list?.length && !selectedRunId) setSelectedRunId(list[0].id);
      } catch {
        setRuns([]);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- Load plan when run changes (identical endpoint used by PlanView)
  useEffect(() => {
    if (!selectedRunId) return;

    (async () => {
      try {
        const bundle: PlanBundle = await loadPlan(selectedRunId); // /runs/:id/plan
        const e = bundle?.epics ?? [];
        const s = (bundle?.stories ?? []).slice().sort((a, b) => (a.priority_rank ?? 0) - (b.priority_rank ?? 0));

        // Flatten tasks from stories; ensure each task has story_id
        const t: Task[] = [];
        for (const st of s) {
          const sid = (st.id || st.story_id || "").toString();
          for (const tk of st.tasks ?? []) {
            t.push({ ...tk, story_id: tk.story_id ?? sid });
          }
        }

        setEpics(e);
        setStories(s);
        setFlatTasks(t);
      } catch (e) {
        // If plan isn't there yet, clear UI (same behaviour as PlanView when no bundle)
        setEpics([]);
        setStories([]);
        setFlatTasks([]);
      } finally {
        // reset selectors on run switch
        setSelectedEpic("");
        setSelectedStoryId("");
      }
    })();
  }, [selectedRunId]);

  // --- Derived helpers from the bundle ---
  const epicTitleById = useMemo(() => {
    const map: Record<string, string> = {};
    for (const e of epics) {
      const id = String((e as any).id ?? ""); // tolerate missing ids
      if (id) map[id] = e.title;
    }
    return map;
  }, [epics]);

  // Map of tasks per story id
  const tasksByStory = useMemo(() => {
    const m = new Map<string, Task[]>();
    for (const t of flatTasks) {
      const sid = (t.story_id || "").toString();
      if (!sid) continue;
      if (!m.has(sid)) m.set(sid, []);
      m.get(sid)!.push(t);
    }
    for (const [, arr] of m) arr.sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
    return m;
  }, [flatTasks]);

  // Selector lists
  const epicOptions = useMemo(() => epics.map((e) => ({ id: (e as any).id?.toString?.() ?? "", title: e.title })), [epics]);

  const storiesInEpic = useMemo(() => {
    if (!selectedEpic) return stories;
    return stories.filter(
      (s) =>
        (s.epic_id && s.epic_id.toString() === selectedEpic) ||
        (s.epic_title && epicTitleById[selectedEpic] === s.epic_title) // fallback for older data
    );
  }, [stories, selectedEpic, epicTitleById]);

  // Counters sourced from the *plan bundle*
  const counts = {
    epics: epics.length,
    stories: stories.length,
    tasks: flatTasks.length,
  };

  // --- Tools ---
  async function handleListTools() {
    if (!selectedRunId) return;
    setLoadingTools(true);
    setTools([]);
    try {
      const res = await fetch(`${API}/code/runs/${selectedRunId}/tools`);
      const data = await res.json();
      const arr = Array.isArray(data?.tools) ? data.tools : Array.isArray(data) ? data : [];
      const names: string[] = arr
        .map((t: any) => (typeof t === "string" ? t : t?.name ?? t?.tool?.name ?? ""))
        .filter(Boolean);
      setTools(names);
    } catch (e: any) {
      setTools([`Error: ${e?.message || e}`]);
    } finally {
      setLoadingTools(false);
    }
  }

  function appendLog(line: string) {
    setLog((prev) => [...prev, `${new Date().toLocaleTimeString()} — ${line}`]);
  }

  // --- Execute story / full run ---
  async function implementStoryById(storyId: string) {
    if (!selectedRunId || !storyId) return;
    const story = stories.find((s) => (s.id || s.story_id)?.toString() === storyId);

    setBusy(true);
    setLastResult(null);
    setLog([]);
    appendLog(`Implementing story: ${story?.title ?? storyId}`);

    try {
      const res = await fetch(
        `${API}/code/runs/${selectedRunId}/story/${encodeURIComponent(storyId)}/implement`,
        { method: "POST", headers: { "Content-Type": "application/json" } }
      );
      const data: ImplementResult = await res.json();
      setLastResult(data);

      const total = data?.results?.length ?? 0;
      const errors = (data?.results || []).filter((r) => r.error).length;
      const ok = (data?.results || []).filter((r) => !r.error).length;

      setProgressByStory((prev) => ({
        ...prev,
        [storyId]: { total, ok, errors },
      }));

      appendLog(`Story done — tasks: ${total}, errors: ${errors}`);
    } catch (e: any) {
      appendLog(`Error: ${e?.message || e}`);
    } finally {
      setBusy(false);
    }
  }

  async function executeWholeRun() {
    if (!selectedRunId) return;
    setBusy(true);
    setLastResult(null);
    setLog([]);
    appendLog(`Executing full plan for run ${selectedRunId}`);
    try {
      const res = await fetch(`${API}/code/runs/${selectedRunId}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await res.json();
      setLastResult(data);
      appendLog(`Run execution response received.`);
    } catch (e: any) {
      appendLog(`Error: ${e?.message || e}`);
    } finally {
      setBusy(false);
    }
  }

  // --- helpers for selected story ---
  const selectedTasks = useMemo(() => {
    if (!selectedStoryId) return [];
    return tasksByStory.get(selectedStoryId) ?? [];
  }, [selectedStoryId, tasksByStory]);

  const selectedProgress =
    progressByStory[selectedStoryId] || { total: selectedTasks.length, ok: 0, errors: 0 };

  const pct =
    selectedProgress.total > 0 ? Math.round((selectedProgress.ok / selectedProgress.total) * 100) : 0;

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Implement Code</h1>
        <Badge>API: {API}</Badge>
      </div>

      <Section
        title="Select Run"
        right={
          <>
            <button
              onClick={executeWholeRun}
              disabled={!selectedRunId || busy}
              className="rounded-xl bg-slate-800 px-3 py-1.5 text-slate-100 hover:bg-slate-700 disabled:opacity-50"
              title="Execute entire plan (all stories & tasks)"
            >
              Execute Plan
            </button>
            <button
              onClick={handleListTools}
              disabled={!selectedRunId || loadingTools}
              className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-1.5 text-slate-100 hover:bg-slate-800 disabled:opacity-50"
              title="Show Serena's bound tools"
            >
              {loadingTools ? "Loading tools..." : "List Tools"}
            </button>
          </>
        }
      >
        <div className="flex flex-wrap items-center gap-3">
          <select
            className="rounded-xl border border-slate-700 bg-slate-800 px-3 py-1.5 text-slate-100"
            value={selectedRunId}
            onChange={(e) => setSelectedRunId(e.target.value)}
          >
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {r.id}
              </option>
            ))}
          </select>
          <Badge>Epics: {counts.epics}</Badge>
          <Badge>Stories: {counts.stories}</Badge>
          <Badge>Tasks: {counts.tasks}</Badge>
        </div>

        {!!tools.length && (
          <div className="mt-3 rounded-xl border border-slate-800 bg-slate-900/60 p-3">
            <div className="mb-1 text-sm font-semibold">Serena Tools</div>
            <div className="flex flex-wrap gap-2">
              {tools.map((n) => (
                <span
                  key={n}
                  className="rounded-md border border-slate-700 bg-slate-800/60 px-2 py-0.5 text-xs text-slate-200 font-mono"
                >
                  {n}
                </span>
              ))}
            </div>
          </div>
        )}
      </Section>

      <Section title="Epics & Stories">
        <div className="grid gap-3 md:grid-cols-3">
          {/* Epic select */}
          <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-3">
            <div className="mb-2 text-sm text-slate-300">Select Epic</div>
            <select
              className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-1.5 text-slate-100"
              value={selectedEpic}
              onChange={(e) => {
                setSelectedEpic(e.target.value);
                setSelectedStoryId("");
              }}
            >
              <option value="">All epics</option>
              {epicOptions.map((e) => (
                <option key={e.id || e.title} value={e.id}>
                  {e.title}
                </option>
              ))}
            </select>
            <div className="mt-2 text-xs text-slate-400">
              Showing {storiesInEpic.length} story(ies)
            </div>
          </div>

          {/* Story select */}
          <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-3">
            <div className="mb-2 text-sm text-slate-300">Select Story</div>
            <select
              className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-1.5 text-slate-100"
              value={selectedStoryId}
              onChange={(e) => setSelectedStoryId(e.target.value)}
            >
              <option value="">—</option>
              {storiesInEpic.map((s) => {
                const sid = (s.id || s.story_id || "").toString();
                return (
                  <option key={sid} value={sid}>
                    {s.title}
                  </option>
                );
              })}
            </select>

            {selectedStoryId && (
              <div className="mt-3">
                <button
                  onClick={() => implementStoryById(selectedStoryId)}
                  disabled={!selectedRunId || busy}
                  className="rounded-xl bg-slate-800 px-3 py-1.5 text-slate-100 hover:bg-slate-700 disabled:opacity-50"
                >
                  Implement Selected Story
                </button>
              </div>
            )}
          </div>

          {/* Progress */}
          <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-3">
            <div className="mb-2 text-sm text-slate-300">Story Progress</div>
            {selectedStoryId ? (
              <>
                <div className="text-xs text-slate-400">
                  {selectedProgress.ok}/{selectedProgress.total} complete • {selectedProgress.errors} errors
                </div>
                <div className="mt-2 h-2 w-full overflow-hidden rounded bg-slate-800">
                  <div className="h-2 bg-emerald-500" style={{ width: `${pct}%` }} />
                </div>
              </>
            ) : (
              <div className="text-xs text-slate-500">Select a story.</div>
            )}
          </div>
        </div>
      </Section>

      <Section title="Stories (all)">
        <div className="grid gap-3 md:grid-cols-2">
          {storiesInEpic.map((s) => {
            const sid = (s.id || s.story_id || "").toString();
            const t = tasksByStory.get(sid) || [];
            const pr = progressByStory[sid] || { total: t.length, ok: 0, errors: 0 };
            const p = pr.total > 0 ? Math.round((pr.ok / pr.total) * 100) : 0;
            const epicName = s.epic_title || (s.epic_id ? epicTitleById[s.epic_id] : "");
            return (
              <div key={`${sid}-${s.title}`} className="rounded-xl border border-slate-700 bg-slate-900/60 p-3">
                <div className="mb-1 text-sm text-slate-400">{epicName}</div>
                <div className="font-semibold">{s.title}</div>
                {s.description && <div className="text-sm text-slate-400">{s.description}</div>}
                <div className="mt-2 flex items-center gap-2">
                  <Badge>Tasks: {t.length}</Badge>
                  <Badge>Done: {pr.ok}</Badge>
                  {pr.errors ? <Badge>Errors: {pr.errors}</Badge> : null}
                </div>
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-slate-800">
                  <div className="h-1.5 bg-emerald-500" style={{ width: `${p}%` }} />
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <button
                    onClick={() => implementStoryById(sid)}
                    disabled={!selectedRunId || busy || !sid}
                    className="rounded-xl bg-slate-800 px-3 py-1.5 text-slate-100 hover:bg-slate-700 disabled:opacity-50"
                  >
                    Implement Story
                  </button>
                </div>
                {!!t.length && (
                  <details className="mt-3">
                    <summary className="cursor-pointer select-none text-sm text-slate-300">
                      View tasks
                    </summary>
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-300">
                      {t.map((task) => (
                        <li key={`${task.task_id || task.id || Math.random()}`}>
                          #{task.order ?? "?"} {task.title || task.description || "(task)"}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            );
          })}
        </div>
      </Section>

      <Section title="Run Log / Result">
        {busy && <div className="mb-2 text-sm text-slate-300">Working… this can take a little while.</div>}
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-3">
            <div className="mb-1 text-sm font-semibold">Log</div>
            <div className="max-h-64 overflow-auto text-sm">
              {log.length ? (
                <ul className="space-y-1 text-slate-300">
                  {log.map((l, i) => (
                    <li key={i} className="whitespace-pre-wrap">
                      {l}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="text-slate-400">No log yet.</div>
              )}
            </div>
          </div>
          <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-3">
            <div className="mb-1 text-sm font-semibold">Last Result</div>
            <div className="max-h-64 overflow-auto text-sm">
              {lastResult ? (
                <pre className="whitespace-pre-wrap rounded border border-slate-800 bg-slate-800/60 p-2 text-slate-200">
                  {JSON.stringify(lastResult, null, 2)}
                </pre>
              ) : (
                <div className="text-slate-400">No result yet.</div>
              )}
            </div>
          </div>
        </div>
      </Section>
    </div>
  );
}
