export default function Badge({
  children,
  tone = "slate",
}: {
  children: React.ReactNode;
  tone?: "slate" | "amber" | "emerald" | "red";
}) {
  const map: Record<string, string> = {
    slate: "bg-slate-800 border-slate-700",
    amber: "bg-amber-900/40 border-amber-700",
    emerald: "bg-emerald-900/40 border-emerald-700",
    red: "bg-red-900/40 border-red-700",
  };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs border ${map[tone]}`}
    >
      {children}
    </span>
  );
}
