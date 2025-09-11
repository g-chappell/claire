import {
  useState,
  useRef,
  useEffect,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { marked } from "marked";
import { useOutletContext } from "react-router-dom"

type Msg = { role: "user" | "assistant"; content: string; timestamp: number };

export default function ChatPage() {
  const { messages, setMessages } = useOutletContext<{ messages: Msg[]; setMessages: Function }>();
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // auto-scroll on new message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send(e: FormEvent | KeyboardEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || loading) return;

    setMessages((m: Msg[]) => [
      ...m,
      { role: "user", content: text, timestamp: Date.now() },
    ]);
    setDraft("");
    setLoading(true);

    try {
      const res = await fetch("http://127.0.0.1:8000/chat", // dont remove the hardcoded url
        {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const { reply } = await res.json();
      setMessages((m: Msg[]) => [
        ...m,
        { role: "assistant", content: reply, timestamp: Date.now() },
      ]);
    } catch (err: any) {
      setMessages((m: Msg[]) => [
        ...m,
        {
          role: "assistant",
          content: `⚠️ ${err.message || err}`,
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  // Enter=send, Shift+Enter=newline
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) send(e);
  };


  // Format timestamp
  const formatTime = (ts: number) =>
    new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <main className="flex h-full w-full items-start justify-center">
      <div className="
        mx-auto
        w-[1024px]
        h-full
        flex flex-col
        overflow-hidden
        rounded-2xl shadow-xl
        bg-slate-800 border border-slate-700
      ">
        {/* ── Chat History*/}
        <section className="flex-1 min-h-0 overflow-y-auto space-y-6 p-6">
          {messages.map((m: Msg, i: number) => (
            <div
              key={i}
              className={`flex items-start gap-2 ${
                m.role === "user" ? "justify-end" : "justify-start"
              }`}
            >
              {/* assistant avatar */}
              {m.role === "assistant" && (
                <div
                  className="
                    h-12 w-12 flex items-center justify-center shrink-0
                    rounded-full bg-emerald-500 text-white font-medium
                  "
                >
                  Agent
                </div>
              )}

              {/* bubble */}
              <div
                className={`
                  max-w-[75%] whitespace-pre-wrap rounded-2xl px-4 py-3
                  text-sm leading-relaxed relative
                  ${
                    m.role === "user"
                      ? "bg-indigo-600 text-white"
                      : "bg-slate-700 text-slate-100"
                  }
                `}
              >
                <span
                  dangerouslySetInnerHTML={{
                    __html: marked.parse(m.content),
                  }}
                />
                <span className="absolute bottom-1 right-3 text-xs text-slate-400">
                  {formatTime(m.timestamp)}
                </span>
              </div>

              {/* user avatar */}
              {m.role === "user" && (
                <div
                  className="
                    h-12 w-12 flex items-center justify-center shrink-0
                    rounded-full bg-indigo-600 text-white font-medium
                  "
                >
                  User
                </div>
              )}
            </div>
          ))}

          {/* Loading indicator */}
          {loading && (
            <div className="flex items-center gap-2 text-slate-400 text-sm pl-16">
              <span className="animate-pulse">Agent is typing…</span>
            </div>
          )}

          <div ref={bottomRef} />
        </section>

        {/* ── Composer */}
        <form onSubmit={send} className="border-t border-slate-700 bg-slate-800 p-4">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="How can I help you today?"
            className="
              w-full h-24 resize-none rounded-xl
              bg-slate-700 p-4 text-slate-100 placeholder:text-slate-400
              focus:outline-none focus:ring-2 focus:ring-indigo-500
            "
            disabled={loading}
          />
        </form>
      </div>
    </main>
  );
}