import { Outlet, useLocation } from "react-router-dom";
import { useState } from "react";

export default function App() {
  const location = useLocation();
  const [messages, setMessages] = useState([]);
  const isChatPage = location.pathname === "/";

  const clearChat = () => setMessages([]);

return (
    <div className="h-screen flex flex-col bg-zinc-900 text-zinc-100 overflow-hidden">
      {/* top bar ---------------------------------------------------- */}
      <header className="fixed top-0 left-0 right-0 z-20 flex items-center border-b border-zinc-700 px-6 py-4 justify-between bg-zinc-900">
        <h1 className="text-xl font-semibold">
          Cognitive Learning Agent for Iterative Reflection and Explanation
        </h1>
        {isChatPage && (
          <button
            type="button"
            onClick={clearChat}
            className="px-3 py-1 rounded-lg bg-slate-700 text-slate-300 hover:bg-slate-600 text-xs"
          >
            Clear Chat
          </button>
        )}
      </header>

      {/* routed pages (ChatPage, SettingsPage, …) ------------------- */}
      <main className="flex-1 flex justify-center items-start pt-[72px] h-full">
        {/* pt-[72px] matches header height (py-4 + px-6) */}
        <Outlet context={{ messages, setMessages }} />
      </main>
    </div>
  );
}