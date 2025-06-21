// src/App.tsx
import { Outlet } from 'react-router-dom';

export default function App() {
  return (
    <div className="min-h-screen grid grid-rows-[auto_1fr] bg-zinc-900 text-zinc-100">
      <header className="px-6 py-4 border-b border-zinc-700 flex items-center">
        <h1 className="text-xl font-semibold">Claire AI Console</h1>
      </header>

      {/* All routed pages render here */}
      <Outlet />
    </div>
  );
}
