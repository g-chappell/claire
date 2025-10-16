import { useEffect, useMemo, useState } from "react";
import {
  createRun,
  deleteRun,
  getRun,
  listRuns,
} from "../lib/api";
import type { RunCreate, RunSummary } from "../types";

type RunDetail = {
  run: { id: string; status: string; started_at?: string | null; finished_at?: string | null };
  manifest?: any;
  requirement?: {
    id: string; title: string; description: string;
    constraints?: string[]; priority?: string; non_functionals?: string[];
  } | null;
};

export default function PlanManageRun() {
  // ----- create form -----
  const [title, setTitle] = useState("");
  const [reqTitle, setReqTitle] = useState("");
  const [reqDesc, setReqDesc] = useState("");
  const [busyCreate, setBusyCreate] = useState(false);

  // placeholders that explain how to fill it in
  const runTitlePH = "Short label, e.g. “Onboarding flow – v1”";
  const reqTitlePH = "As a <persona>, I want <capability> so that <benefit>";
  const reqDescPH = "Describe the requirement in a few sentences. You can list constraints or NFRs if helpful.";

  // ----- runs list / selection -----
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | "">("");
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const selected = useMemo(
    () => runs.find(r => r.id === selectedId),
    [runs, selectedId]
  );

  async function refreshRuns(preserveSelection = false) {
    const list = await listRuns();
    setRuns(list);
    if (!preserveSelection) {
      const id = list[0]?.id ?? "";
      setSelectedId(id);
      if (id) {
        const d = await getRun(id);
        setDetail(d);
      } else {
        setDetail(null);
      }
    } else {
      // if current selection vanished, pick first (or clear)
      if (selectedId && !list.some(r => r.id === selectedId)) {
        const id = list[0]?.id ?? "";
        setSelectedId(id);
        setDetail(id ? await getRun(id) : null);
      }
    }
  }

  useEffect(() => {
    refreshRuns(false).catch(console.error);
  }, []);

  async function onCreate() {
    const payload: RunCreate = {
      title: title.trim() || "(untitled)",
      requirement_title: reqTitle.trim() || "As a user, I want ...",
      requirement_description: reqDesc.trim() || "Describe the requirement…",
      constraints: [],
      priority: "Should",
      non_functionals: [],
    };
    setBusyCreate(true);
    try {
      const { run_id } = await createRun(payload);
      // force a clean refresh and select the new one
      await refreshRuns(true);
      setSelectedId(run_id);
      setDetail(await getRun(run_id));
    } finally {
      setBusyCreate(false);
    }
  }

  async function onSelect(id: string) {
    setSelectedId(id);
    if (!id) { setDetail(null); return; }
    setBusy(true);
    try {
      const d = await getRun(id);
      setDetail(d);
    } finally {
      setBusy(false);
    }
  }

  async function onDelete() {
    if (!selectedId) return;
    const ok = confirm("Delete this run and ALL associated artefacts? This cannot be undone.");
    if (!ok) return;
    setBusy(true);
    try {
      const res = await deleteRun(selectedId);
      // show counts if backend returned them
      if (res.ok && res.deleted) {
        alert(
          `Deleted. (counts)\n` +
          Object.entries(res.deleted).map(([k, v]) => `• ${k}: ${v}`).join("\n")
        );
      }
      // hard refresh list; if current selection disappeared, UI clears accordingly
      setRuns(rs => rs.filter(r => r.id !== selectedId));
      setSelectedId("");
      setDetail(null);
      await deleteRun(selectedId);
      await refreshRuns(false); // list again from backend
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* ===== Create Run ===== */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <h2 className="text-lg font-semibold mb-4">Create Run</h2>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-3">
          <div>
            <label className="block text-sm mb-1 opacity-80">Run title</label>
            <input
              className="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-2"
              placeholder={runTitlePH}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-sm mb-1 opacity-80">Requirement title</label>
            <input
              className="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-2"
              placeholder={reqTitlePH}
              value={reqTitle}
              onChange={(e) => setReqTitle(e.target.value)}
            />
          </div>
        </div>

        <div className="mb-4">
          <label className="block text-sm mb-1 opacity-80">Requirement description</label>
          <textarea
            className="w-full min-h-[120px] rounded-md bg-slate-800 border border-slate-700 px-3 py-2"
            placeholder={reqDescPH}
            value={reqDesc}
            onChange={(e) => setReqDesc(e.target.value)}
          />
        </div>

        <button
          onClick={onCreate}
          disabled={busyCreate}
          className="px-4 py-2 rounded-md bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50"
        >
          {busyCreate ? "Creating…" : "Create Run"}
        </button>
      </section>

      {/* ===== Select / Manage existing runs ===== */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <h2 className="text-lg font-semibold mb-4">Manage Existing Runs</h2>

        <div className="flex items-center gap-2 mb-4">
          <select
            className="min-w-[360px] rounded-md bg-slate-800 border border-slate-700 px-3 py-2"
            value={selectedId}
            onChange={(e) => onSelect(e.target.value)}
          >
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {(r.title || "(untitled)")} — {r.id.slice(0, 8)} — {r.status}
              </option>
            ))}
            {!runs.length && <option value="">(no runs found)</option>}
          </select>

          <button
            onClick={() => refreshRuns(true)}
            className="px-3 py-2 rounded-md bg-slate-700 hover:bg-slate-600"
          >
            Refresh
          </button>

          <button
            onClick={onDelete}
            disabled={!selectedId || busy}
            className="px-3 py-2 rounded-md bg-red-600 hover:bg-red-500 disabled:opacity-50"
          >
            Delete
          </button>
        </div>

        {/* Details Panel */}
        {selected && detail ? (
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4 space-y-4">
            <div>
              <h3 className="font-semibold">Run</h3>
              <div className="text-sm opacity-80">
                <div>ID: {detail.run.id}</div>
                <div>Status: {detail.run.status}</div>
                <div>Started: {detail.run.started_at ?? "—"}</div>
                <div>Finished: {detail.run.finished_at ?? "—"}</div>
              </div>
            </div>

            <div>
              <h3 className="font-semibold">Requirement</h3>
              {detail.requirement ? (
                <div className="text-sm opacity-80 space-y-1">
                  <div><span className="opacity-70">Title: </span>{detail.requirement.title}</div>
                  <div className="opacity-70">Description:</div>
                  <pre className="whitespace-pre-wrap bg-slate-800 rounded p-2 border border-slate-700">
                    {detail.requirement.description}
                  </pre>
                </div>
              ) : (
                <div className="text-sm opacity-60">No requirement persisted.</div>
              )}
            </div>
          </div>
        ) : (
          <div className="text-sm opacity-60">Select a run to view details.</div>
        )}
      </section>
    </div>
  );
}
