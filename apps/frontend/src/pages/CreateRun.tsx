import { useEffect, useState } from "react";
import { createRun, listRuns } from "../lib/api";
import type { RunCreate, RunSummary } from "../types";
import { Link } from "react-router-dom";

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

export default function CreateRun() {
  const [title, setTitle] = useState("");
  const [reqTitle, setReqTitle] = useState("");
  const [reqDesc, setReqDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [delOpen, setDelOpen] = useState(false);
  const [delCounts, setDelCounts] = useState<Record<string, number> | null>(null);
  const API = (import.meta as any).env?.VITE_API_URL ?? "http://127.0.0.1:8000";


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
      const res = await fetch(`${API}/runs/${selectedId}`, { method: "DELETE" });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt || `HTTP ${res.status}`);
      }
      const data = await res.json(); // { ok: true, deleted: { … } }
      setDelCounts(data?.deleted ?? null);
      setDelOpen(true);
      await refresh();
    } catch (e: any) {
      alert(`Delete failed: ${e?.message ?? String(e)}`);
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
            <Modal
        open={delOpen}
        title="Run deleted"
        onClose={() => setDelOpen(false)}
      >
        {delCounts ? (
          <div>
            <div className="opacity-80 mb-2">
              Per-table delete counts for this run:
            </div>
            <table className="w-full text-sm border border-slate-800 rounded overflow-hidden">
              <thead className="bg-slate-950/50">
                <tr>
                  <th className="text-left p-2 border-b border-slate-800">Table</th>
                  <th className="text-right p-2 border-b border-slate-800">Deleted</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(delCounts).map(([k, v]) => (
                  <tr key={k} className="odd:bg-slate-950/30">
                    <td className="p-2">{k}</td>
                    <td className="p-2 text-right tabular-nums">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="opacity-70 text-xs mt-3">
              Action is irreversible.
            </div>
          </div>
        ) : (
          <div className="opacity-80">No counts available.</div>
        )}
      </Modal>
    </div>
  );
}
