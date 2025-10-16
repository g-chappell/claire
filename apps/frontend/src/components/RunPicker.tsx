import { useEffect, useState } from "react";
import { listRuns } from "../lib/api";
import type { RunSummary } from "../types";

export default function RunPicker({
  value, onChange,
}: { value?: string | null; onChange: (id: string | null) => void }) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    try { setRuns(await listRuns()); }
    finally { setLoading(false); }
  }
  useEffect(() => { refresh(); }, []);

  return (
    <div className="flex items-center gap-2">
      <select
        className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">(select a run)</option>
        {runs.map(r => (
          <option key={r.id} value={r.id}>
            {(r.title ?? "(untitled)")} — {r.id.slice(0, 8)}
          </option>
        ))}
      </select>
      <button
        className="px-3 py-2 text-sm rounded bg-slate-700 hover:bg-slate-600"
        onClick={refresh}
        disabled={loading}
      >
        {loading ? "Refreshing…" : "Refresh"}
      </button>
    </div>
  );
}
