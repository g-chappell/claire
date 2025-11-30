import { useState } from "react";

export default function Collapsible({
  title, children, defaultOpen=false
}:{title:string; children:React.ReactNode; defaultOpen?:boolean}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-slate-200 rounded-lg bg-white shadow-sm">
      <button
        className="w-full text-left px-4 py-3 bg-slate-50 hover:bg-slate-100 rounded-t-lg flex justify-between items-center border-b border-slate-200"
        onClick={() => setOpen(v => !v)}
      >
        <span className="font-semibold text-slate-900">{title}</span>
        <span className="text-slate-500">{open ? "−" : "+"}</span>
      </button>
      {open && <div className="p-4 bg-white rounded-b-lg">{children}</div>}
    </div>
  );
}
