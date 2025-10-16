import { useState } from "react";

export default function Collapsible({
  title, children, defaultOpen=false
}:{title:string; children:React.ReactNode; defaultOpen?:boolean}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-slate-700 rounded-lg">
      <button
        className="w-full text-left px-4 py-3 bg-slate-800 hover:bg-slate-700 rounded-t-lg flex justify-between"
        onClick={() => setOpen(v => !v)}
      >
        <span className="font-semibold">{title}</span>
        <span className="opacity-60">{open ? "−" : "+"}</span>
      </button>
      {open && <div className="p-4 bg-slate-900 rounded-b-lg">{children}</div>}
    </div>
  );
}
