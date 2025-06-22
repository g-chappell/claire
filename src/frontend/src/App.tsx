// src/frontend/src/App.tsx
import { Outlet } from "react-router-dom";

export default function App() {
  return (
    <div className="min-h-screen flex flex-col bg-zinc-900 text-zinc-100">
      {/* top bar ---------------------------------------------------- */}
      <header className="flex items-center border-b border-zinc-700 px-6 py-4">
        <h1 className="text-xl font-semibold">Cognitive Learning Agent for Iterative Reflection and Explanation</h1>
      </header>

      {/* routed pages (ChatPage, SettingsPage, …) ------------------- */}
      <main className="flex-1 flex justify-center items-start">
        <Outlet />
      </main>
    </div>
  );
}
