// ...imports...
import { useEffect, useState } from "react";
import { listRuns } from "../lib/api";
import type { RunSummary } from "../types";

type Props = {
  value?: string | null;
  onChange: (id: string | null) => void;
};

export default function RunPicker({ value, onChange }: Props) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const data = await listRuns();
      setRuns(data);
    } finally {
      setLoading(false);
    }
  }

  // Load on mount
  useEffect(() => { refresh(); }, []);

  // Optional: revalidate when tab gains focus
  useEffect(() => {
    const onVis = () => { if (document.visibilityState === "visible") refresh(); };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  return (
    <div className="flex items-center gap-2">
      <select
        className="bg-white border border-slate-300 rounded px-3 py-2 text-sm text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 disabled:bg-slate-100"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        disabled={loading && runs.length === 0}
      >
        <option value="">(select a run)</option>
        {runs.map((r) => (
          <option key={r.id} value={r.id}>
            {(r.title?.trim() ? r.title : "(untitled)")} — {r.id.slice(0, 8)}
            {r.status ? ` — ${r.status}` : ""}
          </option>
        ))}
      </select>
      {/* Refresh button removed */}
    </div>
  );
}
