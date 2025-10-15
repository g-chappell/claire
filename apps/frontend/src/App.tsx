import "highlight.js/styles/atom-one-dark.css";

// src/App.tsx
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

type Msg = { role: "user" | "assistant"; content: string; timestamp: number };

export default function App() {
  const [messages, setMessages] = useState<Msg[]>([]);

  const linkBase =
    "px-3 py-2 rounded-lg text-sm font-medium transition";
  const active = "bg-slate-700 text-white";
  const idle   = "text-slate-300 hover:bg-slate-700/60";

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 flex">
      {/* Sidebar Nav */}
      <aside className="w-64 border-r border-slate-800 p-4 space-y-4">
        <h1 className="text-xl font-semibold">CLAIRE</h1>
        <nav className="flex flex-col gap-2">
          <NavLink to="/chat" className={({isActive}) => `${linkBase} ${isActive?active:idle}`}>Chat</NavLink>
          <NavLink to="/plan" className={({isActive}) => `${linkBase} ${isActive?active:idle}`}>Plan</NavLink>
          <NavLink to="/implement" className={({isActive}) => `${linkBase} ${isActive?active:idle}`}>Implement</NavLink>
          <NavLink to="/review" className={({isActive}) => `${linkBase} ${isActive?active:idle}`}>Review</NavLink>
          <NavLink to="/settings" className={({isActive}) => `${linkBase} ${isActive?active:idle}`}>Settings</NavLink>
        </nav>
      </aside>

      {/* Main content */}
      <div className="flex-1 min-w-0">
        <Outlet context={{ messages, setMessages }} />
      </div>
    </div>
  );
}
