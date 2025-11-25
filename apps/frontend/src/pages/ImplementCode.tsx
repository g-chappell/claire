// src/pages/ImplementCode.tsx
import React, { useEffect, useMemo, useState } from "react";
import { listRuns as apiListRuns, getPlan as loadPlan } from "../lib/api"; // ← same helpers PlanView uses

// Loosely-typed to tolerate older bundles
type RunLite = { id: string; created_at?: string; title?: string };

type Epic = {
  id?: string;
  title: string;
  description?: string;
  priority_rank?: number;
  depends_on?: string[];
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
  epic_title?: string; // legacy
  title: string;
  description?: string;
  priority_rank?: number;
  depends_on?: string[];   // NEW
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
    events?: any[]; // ← backend already returns LC events; we’ll parse these
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

// Small clickable chip for dependencies
function DepChip({
  label,
  onClick,
  title,
}: {
  label: string;
  onClick?: () => void;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="inline-flex items-center gap-1 rounded-md border border-amber-600/60 bg-amber-900/20 px-2 py-0.5 text-xs text-amber-200 hover:bg-amber-900/30"
    >
      <span aria-hidden>🔗</span>
      {label}
    </button>
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
  const [workingStoryTitle, setWorkingStoryTitle] = useState<string>("");

  // Live progress (SSE)
  const [streaming, setStreaming] = useState(false);
  const [currentTaskId, setCurrentTaskId] = useState<string>("");
  const [toolCountsByTask, setToolCountsByTask] = useState<Record<string, number>>({});
  const [latestToolByTask, setLatestToolByTask] = useState<Record<string, string>>({});
  const [es, setEs] = useState<EventSource | null>(null);
  

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

  // Clean up any open EventSource on unmount or when 'es' changes
  useEffect(() => {
    return () => {
      if (es) {
        try { es.close(); } catch {}
      }
    };
  }, [es]);

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
        // reset selectors & progress on run switch
        setSelectedEpic("");
        setSelectedStoryId("");
        setProgressByStory({});
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

  const depStats = useMemo(() => {
  const epicDeps = (epics ?? []).filter(
      e => Array.isArray((e as any).depends_on) && (e as any).depends_on.length > 0
    ).length;
    const storyDeps = (stories ?? []).filter(
      s => Array.isArray((s as any).depends_on) && (s as any).depends_on.length > 0
    ).length;
    return { epicDeps, storyDeps };
  }, [epics, stories]);

  // Rank lookup for epics
  const epicRankById = useMemo(() => {
    const map: Record<string, number> = {};
    for (const e of epics) {
      const id = String((e as any).id ?? "");
      if (id) map[id] = (e as any).priority_rank ?? 0;
    }
    return map;
  }, [epics]);

  const storyTitleById = useMemo(() => {
    const map: Record<string, string> = {};
    for (const s of stories) {
      const id = String((s.id ?? s.story_id ?? "") || "");
      if (id) map[id] = s.title;
    }
    return map;
  }, [stories]);

  // NEW: dependencies of the currently-selected story, coerced to string IDs
  const depsOfSelected = useMemo(() => {
    if (!selectedStoryId) return new Set<string>();
    const s = stories.find(st => String(st.id ?? st.story_id ?? "") === selectedStoryId);
    const raw = Array.isArray((s as any)?.depends_on) ? (s as any).depends_on : [];
    return new Set<string>(raw.map((d: any) => String(d)));
  }, [selectedStoryId, stories]);

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

  // --- Ordered plan views (epics then stories) ---
  const epicsOrdered = useMemo(
    () => (epics ?? []).slice().sort((a, b) => (a.priority_rank ?? 0) - (b.priority_rank ?? 0)),
    [epics]
  );

  const storiesByEpicOrdered = useMemo(() => {
    const m = new Map<string, Story[]>();
    const orderedStories = (stories ?? []).slice().sort(
      (a, b) => (a.priority_rank ?? 0) - (b.priority_rank ?? 0)
    );
    for (const s of orderedStories) {
      const eid = (s.epic_id ?? "").toString();
      if (!m.has(eid)) m.set(eid, []);
      m.get(eid)!.push(s);
    }
    return m;
  }, [stories]);

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

  function bumpToolCount(taskId: string, toolName?: string) {
    if (!taskId) return;
    setToolCountsByTask(prev => ({ ...prev, [taskId]: (prev[taskId] ?? 0) + 1 }));
    if (toolName) setLatestToolByTask(prev => ({ ...prev, [taskId]: toolName }));
  }

  // When a task completes, update per-story progress immediately
  function markTaskFinished(storyId: string, ok: boolean) {
    if (!storyId) return;
    setProgressByStory(prev => {
      const cur = prev[storyId] ?? { total: (tasksByStory.get(storyId)?.length ?? 0), ok: 0, errors: 0 };
      return {
        ...prev,
        [storyId]: {
          total: cur.total,
          ok: cur.ok + (ok ? 1 : 0),
          errors: cur.errors + (ok ? 0 : 1),
        },
      };
    });
  }

  // --- Execute story / full run ---

  async function tryStreamStory(
    storyId: string,
    onSseErrorFallback: () => Promise<void>
  ): Promise<boolean> {
    if (!selectedRunId) return false;

    // Close any previous stream before starting a new one
    if (es) {
      try { es.close(); } catch {}
      setEs(null);
    }

    const url = `${API}/code/runs/${selectedRunId}/story/${encodeURIComponent(storyId)}/implement/stream`;

    try {
      const source = new EventSource(url);
      setEs(source);
      setStreaming(true);

      // Reset per-task diagnostics for this story
      setToolCountsByTask({});
      setLatestToolByTask({});
      setCurrentTaskId("");

      source.onmessage = (e) => {
        try {
          const evt = JSON.parse(e.data);

          if (evt?.event === "on_tool_start") {
            const tId = String(evt.task_id ?? "");
            setCurrentTaskId(tId || "");
            bumpToolCount(tId, evt?.name);
            appendLog(`▶ tool: ${evt?.name || "(unknown)"} on task ${tId || "?"}`);
          } else if (evt?.event === "on_tool_end") {
            appendLog(`✔ tool done: ${evt?.name || "(unknown)"}`);
          } else if (evt?.event === "task_complete") {
            const tId = String(evt.task_id ?? "");
            const ok = !!evt?.ok;
            markTaskFinished(storyId, ok);
            appendLog(`✓ task ${tId || "?"} ${ok ? "OK" : "ERROR"}`);
          } else if (evt?.event === "story_begin") {
            appendLog(`Story started…`);
          } else if (evt?.event === "story_end") {
            if (evt?.result) setLastResult(evt.result);
            appendLog(`Story finished.`);
            try { source.close(); } catch {}
            setStreaming(false);
            setBusy(false);
            setWorkingStoryTitle("");
          } else if (evt?.event) {
            appendLog(`event: ${evt.event}`);
          }
        } catch (err: any) {
          appendLog(`Bad event payload: ${err?.message || err}`);
        }
      };

      source.onerror = async () => {
        appendLog("SSE failed — falling back to POST.");
        try { source.close(); } catch {}
        setStreaming(false);
        // keep busy true; the fallback will conclude it
        await onSseErrorFallback();
      };

      return true;
    } catch {
      return false;
    }
  }


async function implementStoryById(storyId: string) {
  if (!selectedRunId || !storyId) return;
    const story = stories.find((s) => (s.id || s.story_id)?.toString() === storyId);

    setBusy(true);
    setWorkingStoryTitle(story?.title ?? storyId);
    setLastResult(null);
    setLog([]);
    appendLog(`Implementing story: ${story?.title ?? storyId}`);

    // Try SSE first
    const doPostFallback = async () => {
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
      setWorkingStoryTitle("");
    }
  };

const sseStarted = await tryStreamStory(storyId, doPostFallback);
if (sseStarted) {
  // Leave busy=true. We'll clear it on 'story_end' or in doPostFallback.
  return;
}

// If SSE couldn't be started at all, use the same POST fallback now.
await doPostFallback();
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

    // Parse LC event stream entries for tool diagnostics
  function summarizeTaskDiagnostics(taskResult: any) {
    const events = Array.isArray(taskResult?.events) ? taskResult.events : [];
    const toolStarts = events.filter((e: any) => e?.event === "on_tool_start");
    const toolEnds = events.filter((e: any) => e?.event === "on_tool_end");

    const totalToolCalls = Math.max(toolStarts.length, toolEnds.length);
    // Try to pull a "latest tool" name from the end event; fall back to start
    const lastEnd = toolEnds[toolEnds.length - 1];
    const lastStart = toolStarts[toolStarts.length - 1];
    const latestName = (lastEnd?.name || lastEnd?.tool_name || lastStart?.name || lastStart?.tool_name || "") as string;

    // Optional: pull a short args preview
    const payload =
      lastEnd?.data?.input ??
      lastEnd?.data?.kwargs ??
      lastStart?.data?.input ??
      lastStart?.data?.kwargs ??
      undefined;

    return { totalToolCalls, latestName, latestArgsPreview: payload };
  }

  function coerceTextLike(val: any): string {
  if (typeof val === "string") {
    // Try to extract a 'title' from python-ish dicts e.g. "{'title': '…', ...}"
    const m = val.match(/'title'\s*:\s*'([^']+)'/);
    if (m) return m[1];
    try {
      const parsed = JSON.parse(val);
      if (parsed && typeof parsed.title === "string") return parsed.title;
    } catch {}
    return val;
  }
  if (val && typeof val === "object") {
    return val.title ?? val.name ?? val.text ?? JSON.stringify(val);
  }
  return String(val ?? "");
}

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Implement Code</h1>
        <Badge>API: {API}</Badge>
      </div>
        {(busy || streaming) && (
          <div className="rounded-xl border border-amber-600 bg-amber-900/30 p-3 text-amber-200">
            Working on: <span className="font-semibold">{workingStoryTitle || "story…"}</span>
          </div>
        )}

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
          <Badge>Epics w/ deps: {depStats.epicDeps}</Badge>
          <Badge>Stories w/ deps: {depStats.storyDeps}</Badge>
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

      {/* High-level execution order */}
      <Section title="Implementation Plan">
          <div className="overflow-x-auto rounded-xl border border-slate-800">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-800/60 text-slate-200">
                <tr>
                  <th className="px-3 py-2 text-left">Order</th>
                  <th className="px-3 py-2 text-left">Epic</th>
                  <th className="px-3 py-2 text-left">Stories (ordered)</th>
                </tr>
              </thead>
              <tbody className="bg-slate-900/40 text-slate-300">
                {epicsOrdered.map((e, i) => {
                  const eid = ((e as any).id ?? "").toString();
                  const erank = (e as any).priority_rank ?? i + 1;
                  const eDeps = Array.isArray((e as any).depends_on) ? (e as any).depends_on.map((d:any) => String(d)) : [];
                  const storiesForEpic = storiesByEpicOrdered.get(eid) || [];
                  return (
                    <tr key={eid || e.title} className="border-t border-slate-800 align-top">
                      <td className="px-3 py-2">#{erank}</td>
                      <td className="px-3 py-2">
                        <div className="font-medium flex items-center gap-2">
                          <span>{e.title}</span>
                          {eDeps.length ? (
                            <span className="rounded bg-amber-800/60 px-1.5 py-0.5 text-[10px]">deps:{eDeps.length}</span>
                          ) : null}
                        </div>
                        {eDeps.length ? (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {eDeps.map((id: string) => {
                              const label = epicTitleById[id] || id;
                              return (
                                <DepChip
                                  key={id}
                                  label={label}
                                  title={`Depends on epic: ${label}`}
                                  onClick={() => setSelectedEpic(id)}
                                />
                              );
                            })}
                          </div>
                        ) : null}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap gap-2">
                          {storiesForEpic.map((s) => {
                            const sid = (s.id || s.story_id || "").toString();
                            const sRank = (s.priority_rank ?? 0) || 0;
                            const sDeps = Array.isArray((s as any).depends_on) ? (s as any).depends_on.map((d:any) => String(d)) : [];
                            const depsTitle = sDeps.map((id: string) => storyTitleById[id] || id).join(", ");
                            return (
                              <button
                                key={`${eid}-${sid}`}
                                className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs ${
                                  sDeps.length
                                    ? "border-amber-600/70 bg-amber-900/20 text-amber-200 hover:bg-amber-900/30"
                                    : "border-slate-700 bg-slate-800/60 text-slate-200 hover:bg-slate-800"
                                } ${selectedStoryId === sid ? "ring-1 ring-slate-400/50" : ""} ${depsOfSelected.has(sid) ? "ring-1 ring-amber-400/60" : ""}`}
                                title={sDeps.length ? `Depends on: ${depsTitle}` : "No declared dependencies"}
                                onClick={() => {
                                  setSelectedEpic(eid);
                                  setSelectedStoryId(sid);
                                }}
                              >
                                #{sRank || "?"} — {s.title}
                                {sDeps.length ? (
                                  <span className="ml-1 rounded bg-amber-800/60 px-1.5 py-0.5 text-[10px]">
                                    deps:{sDeps.length}
                                  </span>
                                ) : null}
                              </button>
                            );
                          })}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Section>

        {/* Focus view for the chosen story */}
        <Section title="Selected Story">
          {!selectedStoryId ? (
            <div className="text-slate-400">Select an epic and story above to view details and implement.</div>
          ) : (() => {
            const s = stories.find((st) => (st.id || st.story_id)?.toString() === selectedStoryId);
            const t = selectedTasks;
            const pr = selectedProgress;
            const epicName = s?.epic_title || (s?.epic_id ? epicTitleById[s.epic_id] : "");
            const sDeps = Array.isArray((s as any)?.depends_on) ? (s as any).depends_on.map((d:any) => String(d)) : [];
            const p = pr.total > 0 ? Math.round((pr.ok / pr.total) * 100) : 0;

            return (
              <div className="space-y-3">
                <div className="mb-1 text-sm text-slate-400">{epicName}</div>
                <div className="text-xl font-semibold">{s?.title}</div>

                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                  {s?.epic_id && epicRankById[s.epic_id] ? <Badge>Epic #{epicRankById[s.epic_id]}</Badge> : null}
                  {typeof s?.priority_rank === "number" ? <Badge>Story #{s?.priority_rank}</Badge> : null}
                    {sDeps.length ? (
                      <div className="flex flex-wrap items-center gap-1">
                        <span className="text-slate-400">Depends on:</span>
                        {sDeps.map((id: string) => {
                          const label = storyTitleById[id] || id;
                          return (
                            <DepChip
                              key={id}
                              label={label}
                              title={`Open story: ${label}`}
                              onClick={() => {
                                setSelectedEpic(String(s?.epic_id ?? ""));
                                setSelectedStoryId(id);
                              }}
                            />
                          );
                        })}
                      </div>
                    ) : null}
                </div>

                {s?.description && <div className="text-sm text-slate-300">{s.description}</div>}

                <div className="flex items-center gap-2">
                  <Badge>Tasks: {t.length}</Badge>
                  <Badge>Done: {pr.ok}</Badge>
                  {pr.errors ? <Badge>Errors: {pr.errors}</Badge> : null}
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded bg-slate-800">
                  <div className="h-1.5 bg-emerald-500" style={{ width: `${p}%` }} />
                </div>

                <div>
                  <button
                    onClick={() => implementStoryById(selectedStoryId)}
                    disabled={!selectedRunId || busy}
                    className="rounded-xl bg-slate-800 px-3 py-1.5 text-slate-100 hover:bg-slate-700 disabled:opacity-50"
                  >
                    Implement Selected Story
                  </button>
                </div>

                {!!t.length && (
                  <div className="overflow-x-auto rounded-lg border border-slate-800">
                    <table className="min-w-full text-sm">
                      <thead className="bg-slate-800/60 text-slate-200">
                        <tr>
                          <th className="px-3 py-2 text-left">Order</th>
                          <th className="px-3 py-2 text-left">Title</th>
                          <th className="px-3 py-2 text-left">Status</th>
                          <th className="px-3 py-2 text-left">Tool Calls</th>
                          <th className="px-3 py-2 text-left">Latest Tool</th>
                        </tr>
                      </thead>
                      <tbody className="bg-slate-900/40 text-slate-300">
                        {t.map((task, idx) => {
                          const rid = lastResult?.results?.find(
                            (r) => (r.task_id || "") === (task.task_id || task.id)
                          );
                          let diag = rid ? summarizeTaskDiagnostics(rid) : { totalToolCalls: 0, latestName: "" };
                          const liveCalls = toolCountsByTask[task.task_id || task.id || ""] ?? 0;
                          const liveLatest = latestToolByTask[task.task_id || task.id || ""];
                          if (streaming && (liveCalls > 0 || liveLatest)) {
                            diag = {
                              totalToolCalls: Math.max(diag.totalToolCalls, liveCalls),
                              latestName: liveLatest || diag.latestName,
                            };
                          }
                          const isLive = streaming && (currentTaskId === (task.task_id || task.id));
                          const status = isLive ? "Working…" : rid ? (rid.error ? "Error" : "OK") : "—";

                          return (
                            <tr key={`${task.task_id || task.id || Math.random()}`} className="border-t border-slate-800">
                              <td className="px-3 py-2">{task.order ?? idx + 1}</td>
                              <td className="px-3 py-2">
                                {coerceTextLike(task.title) || coerceTextLike(task.description) || "(task)"}
                              </td>
                              <td className="px-3 py-2">
                                {status === "OK" ? (
                                  <span className="rounded-md bg-emerald-800/50 px-2 py-0.5 text-emerald-200">OK</span>
                                ) : status === "Error" ? (
                                  <span className="rounded-md bg-rose-800/40 px-2 py-0.5 text-rose-200">Error</span>
                                ) : (
                                  <span className="rounded-md bg-slate-800/50 px-2 py-0.5 text-slate-300">—</span>
                                )}
                              </td>
                              <td className="px-3 py-2">{diag.totalToolCalls}</td>
                              <td className="px-3 py-2 font-mono">{diag.latestName || "—"}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })()}
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
