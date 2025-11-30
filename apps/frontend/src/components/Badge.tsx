export default function Badge({
  children,
  tone = "slate",
}: {
  children: React.ReactNode;
  tone?: "slate" | "amber" | "emerald" | "red";
}) {
    const map: Record<string, string> = {
      slate: "bg-slate-100 border-slate-200 text-slate-800",
      amber: "bg-amber-50 border-amber-200 text-amber-800",
      emerald: "bg-emerald-50 border-emerald-200 text-emerald-800",
      red: "bg-red-50 border-red-200 text-red-800",
    };
    return (
      <span
        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs border font-medium ${map[tone]}`}
      >
        {children}
      </span>
    );
}
