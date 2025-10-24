import { useEffect, useState } from "react";
import { createRun, deleteRun, listRuns } from "../lib/api";
import type { RunCreate, RunSummary } from "../types";
import { Link } from "react-router-dom";

export default function CreateRun() {
  const [title, setTitle] = useState("");
  const [reqTitle, setReqTitle] = useState("");
  const [reqDesc, setReqDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");

  async function refresh() {
    const list = await listRuns();
    setRuns(list);
    setSelectedId(list[0]?.id ?? "");
  }

  useEffect(() => { refresh().catch(console.error); }, []);

  async function onCreate() {
    const payload: RunCreate = {
      title: title.trim() || "(untitled)",
      requirement_title: reqTitle.trim() || "As a user, I want …",
      requirement_description: reqDesc.trim() || "Describe the requirement…",
      constraints: [],
      priority: "Should",
      non_functionals: [],
    };
    setBusy(true);
    try {
      await createRun(payload);
      await refresh();
      setTitle(""); setReqTitle(""); setReqDesc("");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete() {
    if (!selectedId) return;
    if (!confirm("Delete this run and ALL associated artefacts?")) return;
    setBusy(true);
    try {
      await deleteRun(selectedId);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Create Run</h1>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-3">
          <div>
            <label className="block text-sm mb-1 opacity-80">Run title</label>
            <input className="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-2"
                   placeholder='Short label, e.g. "Onboarding flow — v1"'
                   value={title} onChange={e=>setTitle(e.target.value)} />
          </div>
          <div>
            <label className="block text-sm mb-1 opacity-80">Requirement title</label>
            <input className="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-2"
                   placeholder="As a <persona>, I want <capability> so that <benefit>"
                   value={reqTitle} onChange={e=>setReqTitle(e.target.value)} />
          </div>
        </div>
        <div className="mb-4">
          <label className="block text-sm mb-1 opacity-80">Requirement description</label>
          <textarea className="w-full min-h-[120px] rounded-md bg-slate-800 border border-slate-700 px-3 py-2"
                    placeholder="Describe the requirement…"
                    value={reqDesc} onChange={e=>setReqDesc(e.target.value)} />
        </div>
        <button onClick={onCreate} disabled={busy}
                className="px-4 py-2 rounded-md bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50">
          {busy ? "Creating…" : "Create Run"}
        </button>
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <h2 className="text-lg font-semibold mb-3">Delete an existing run</h2>
        <div className="flex gap-2 items-center">
          <select className="min-w-[360px] rounded-md bg-slate-800 border border-slate-700 px-3 py-2"
                  value={selectedId} onChange={e=>setSelectedId(e.target.value)}>
            {runs.map(r => <option key={r.id} value={r.id}>
              {(r.title || "(untitled)")} — {r.id.slice(0,8)} — {r.status}
            </option>)}
            {!runs.length && <option value="">(no runs found)</option>}
          </select>
          <button onClick={onDelete} disabled={!selectedId || busy}
                  className="px-3 py-2 rounded-md bg-red-600 hover:bg-red-500 disabled:opacity-50">
            Delete
          </button>
          <Link to="/plan/manage" className="px-3 py-2 rounded-md bg-slate-700 hover:bg-slate-600">
            Go to Manage
          </Link>
        </div>
      </section>
    </div>
  );
}
