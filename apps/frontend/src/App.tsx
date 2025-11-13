import "highlight.js/styles/atom-one-dark.css";

import { NavLink, Outlet } from "react-router-dom";

import { useChat } from "./useChat";

const link = "block px-4 py-2 rounded hover:bg-slate-800";
const active = "bg-slate-800";

export default function App() {
  const chat = useChat();

  return (
    <div className="min-h-screen grid grid-cols-[240px_1fr] bg-slate-950 text-slate-100">
      <aside className="border-r border-slate-800 p-4 space-y-4">
        <div className="text-xl font-bold">CLAIRE</div>
        <nav className="space-y-2">
          <NavLink to="/chat" className={({isActive})=> `${link} ${isActive?active:""}`}>Chat</NavLink>

          <div className="mt-4 text-xs uppercase tracking-wide opacity-60 px-4">Plan</div>
          <NavLink to="/plan/create"   className={({isActive})=> `${link} ${isActive?active:""}`}>Create Run</NavLink>
          <NavLink to="/plan/manage"   className={({isActive})=> `${link} ${isActive?active:""}`}>Manage Run</NavLink>
          <NavLink to="/plan/generate" className={({isActive})=> `${link} ${isActive?active:""}`}>Generate Plan</NavLink>
          <NavLink to="/plan/view"     className={({isActive})=> `${link} ${isActive?active:""}`}>View Plan</NavLink>

          <div className="mt-4 text-xs uppercase tracking-wide opacity-60 px-4">Execution</div>
          <NavLink to="/implement" className={({isActive})=> `${link} ${isActive?active:""}`}>Implement</NavLink>

          <div className="mt-4 text-xs uppercase tracking-wide opacity-60 px-4">Review</div>
          <NavLink to="/review"    className={({isActive})=> `${link} ${isActive?active:""}`}>Retrospective</NavLink>

          <div className="mt-4 text-xs uppercase tracking-wide opacity-60 px-4">Configuration</div>
          <div className="mt-4"></div>
          <NavLink to="/settings" className={({isActive})=> `${link} ${isActive?active:""}`}>Settings</NavLink>
        </nav>
      </aside>
      <main className="p-6">
        <Outlet context={chat}/>
      </main>
    </div>
  );
}

