export default function StatPill({ label, value }:{label:string; value:number|string}) {
  return (
    <span className="inline-flex items-center gap-2 bg-slate-800 border border-slate-700 rounded-full px-3 py-1 text-xs">
      <span className="opacity-75">{label}</span>
      <span className="font-semibold">{value}</span>
    </span>
  );
}
