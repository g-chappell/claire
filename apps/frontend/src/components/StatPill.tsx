export default function StatPill({ label, value }:{label:string; value:number|string}) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-slate-100 border border-slate-200 px-3 py-1 text-xs text-slate-800">
      <span className="opacity-70">{label}</span>
      <span className="font-semibold text-slate-900">{value}</span>
    </span>
  );
}
