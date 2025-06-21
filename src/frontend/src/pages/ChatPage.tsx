// src/pages/ChatPage.tsx
export default function ChatPage() {
  return (
    <main className="p-6 flex flex-col gap-4">
      {/* message list */}
      <section className="flex-1 overflow-y-auto space-y-4">
        {/* …messages mapped here… */}
      </section>

      {/* composer */}
      <form className="flex gap-2" onSubmit={() => { /* no-op  */ }}>
        <textarea
          className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg p-3
                     focus:outline-none focus:ring-2 focus:ring-indigo-500"
          rows={2}
          placeholder="Ask the agent…"
        />
        <button
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-lg">
          Send
        </button>
      </form>
    </main>
  );
}
