// apps/frontend/src/pages/Retrospective.tsx
import { useEffect, useMemo, useState } from "react";
import { BASE, patchFeedback, synthesizeAIFeedback, type Kind } from "../lib/api";

type RunLite = { id: string; title?: string };
type Epic = { id: string; title: string; description?: string; feedback_human?: string; feedback_ai?: string };
type Story = { id: string; epic_id?: string; title: string; description?: string; feedback_human?: string; feedback_ai?: string };
type Task = { id: string; story_id?: string; title: string; feedback_human?: string; feedback_ai?: string };

export default function RetrospectivePage() {
  const [runs, setRuns] = useState<RunLite[]>([]);
  const [runId, setRunId] = useState("");

  const [epics, setEpics] = useState<Epic[]>([]);
  const [stories, setStories] = useState<Story[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);

  const [kind, setKind] = useState<Kind>("epic");
  const [selectedId, setSelectedId] = useState("");

  const [human, setHuman] = useState("");
  const [ai, setAI] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const r = await fetch(`${BASE}/runs`);
      const data = await r.json();
      setRuns(Array.isArray(data) ? data : []);
      if (Array.isArray(data) && data[0]?.id) setRunId(data[0].id);
    })();
  }, []);

  useEffect(() => {
    if (!runId) return;
    (async () => {
      // load plan entities via your existing endpoints
      const [eRes, sRes, tRes] = await Promise.all([
        fetch(`${BASE}/plan/runs/${runId}/epics`).catch(() => null),
        fetch(`${BASE}/plan/runs/${runId}/stories`).catch(() => null),
        fetch(`${BASE}/plan/runs/${runId}/tasks`).catch(() => null),
      ]);
      const [e, s, t] = await Promise.all([
        eRes?.ok ? eRes.json() : [],
        sRes?.ok ? sRes.json() : [],
        tRes?.ok ? tRes.json() : [],
      ]);
      setEpics(e || []);
      setStories(s || []);
      setTasks(t || []);
      setSelectedId("");
      setHuman("");
      setAI("");
    })();
  }, [runId]);

  const candidates = useMemo(() => {
    if (kind === "epic") return epics.map(x => ({ id: x.id, label: x.title, human: x.feedback_human, ai: x.feedback_ai }));
    if (kind === "story") return stories.map(x => ({ id: x.id, label: x.title, human: x.feedback_human, ai: x.feedback_ai }));
    return tasks.map(x => ({ id: x.id, label: x.title, human: x.feedback_human, ai: x.feedback_ai }));
  }, [kind, epics, stories, tasks]);

  useEffect(() => {
    const chosen = candidates.find(c => c.id === selectedId);
    setHuman(chosen?.human || "");
    setAI(chosen?.ai || "");
  }, [selectedId, candidates]);

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

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4">
      <h1 className="text-2xl font-bold">Retrospective & Feedback</h1>

      <section className="rounded-xl border border-slate-700 bg-slate-900 p-4">
        <div className="grid gap-3 md:grid-cols-3">
          <div>
            <div className="mb-1 text-sm text-slate-300">Run</div>
            <select
              className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-1.5 text-slate-100"
              value={runId}
              onChange={e => setRunId(e.target.value)}
            >
              {runs.map(r => <option key={r.id} value={r.id}>{r.id}</option>)}
            </select>
          </div>

          <div>
            <div className="mb-1 text-sm text-slate-300">Artefact type</div>
            <select
              className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-1.5 text-slate-100"
              value={kind}
              onChange={e => { setKind(e.target.value as Kind); setSelectedId(""); }}
            >
              <option value="epic">Epic</option>
              <option value="story">Story</option>
              <option value="task">Task</option>
            </select>
          </div>

          <div>
            <div className="mb-1 text-sm text-slate-300">Artefact</div>
            <select
              className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-1.5 text-slate-100"
              value={selectedId}
              onChange={e => setSelectedId(e.target.value)}
            >
              <option value="">—</option>
              {candidates.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
            </select>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-slate-700 bg-slate-900 p-4">
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <div className="mb-1 text-sm font-semibold">Human feedback</div>
            <textarea
              className="h-48 w-full rounded-xl border border-slate-700 bg-slate-800 p-2 text-slate-100"
              value={human}
              onChange={e => setHuman(e.target.value)}
              placeholder="Add actionable critique, constraints, risks, priorities…"
            />
            <div className="mt-2 flex gap-2">
              <button
                onClick={saveHuman}
                disabled={!runId || !selectedId || busy}
                className="rounded-xl bg-slate-800 px-3 py-1.5 text-slate-100 hover:bg-slate-700 disabled:opacity-50"
              >
                Save human feedback
              </button>
              <button
                onClick={genAI}
                disabled={!runId || !selectedId || busy}
                className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-1.5 text-slate-100 hover:bg-slate-800 disabled:opacity-50"
              >
                Generate AI feedback
              </button>
            </div>
          </div>
          <div>
            <div className="mb-1 text-sm font-semibold">AI feedback</div>
            <textarea
              className="h-48 w-full rounded-xl border border-slate-700 bg-slate-800 p-2 text-slate-100"
              value={ai}
              onChange={e => setAI(e.target.value)}
              placeholder="AI synthesis will appear here…"
            />
            <div className="mt-2">
              <button
                onClick={() => patchFeedback(runId, kind, selectedId, { ai })}
                disabled={!runId || !selectedId || busy}
                className="rounded-xl bg-slate-800 px-3 py-1.5 text-slate-100 hover:bg-slate-700 disabled:opacity-50"
              >
                Save AI feedback
              </button>
            </div>
          </div>
        </div>
        {msg && <div className="mt-3 text-sm text-slate-300">{msg}</div>}
      </section>
    </div>
  );
}
