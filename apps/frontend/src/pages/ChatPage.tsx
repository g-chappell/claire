// src/pages/ChatPage.tsx
import {
  useState, useRef, useEffect, type FormEvent, type KeyboardEvent,
} from "react";
import { marked } from "marked";
import hljs from "highlight.js";
import { useOutletContext } from "react-router-dom";
import { useChat } from "../useChat";

// Configure markdown + code highlighting
marked.setOptions({
  // @ts-ignore
  highlight(code: string, lang: string) {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(code, { language: lang }).value;
    }
    return hljs.highlightAuto(code).value;
  },
  gfm: true,
  breaks: true,
} as any);

export default function ChatPage() {
  // Prefer chat context provided by <App/>, fall back to a local hook
  const ctx = useOutletContext<ReturnType<typeof useChat> | undefined>();
  const local = useChat();
  const { messages, send, loading } = ctx ?? local;

  // derive the exact element type from the hook to avoid mismatches
  type ChatMessage = (typeof messages)[number];

  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // add language labels on code blocks
    document.querySelectorAll(".prose pre code").forEach((block) => {
      const pre = block.parentElement;
      if (!pre) return;
      pre.querySelector(".code-lang-label")?.remove();
      const lang = Array.from(block.classList)
        .find((c) => c.startsWith("language-"))
        ?.replace("language-", "");
      if (lang) {
        const label = document.createElement("div");
        label.className = "code-lang-label";
        label.textContent = lang;
        pre.appendChild(label);
      }
    });
    hljs.highlightAll();
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function onSend(e: FormEvent | KeyboardEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || loading) return;
    await send(text);
    setDraft("");
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) onSend(e);
  };

  const formatTime = (ts: number) =>
    new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <main className="flex h-full w-full items-start justify-center">
      <div className="mx-auto w-[1024px] h-full flex flex-col overflow-hidden rounded-2xl shadow-xl bg-white border border-slate-200">
        {/* History */}
        <section className="flex-1 min-h-0 overflow-y-auto space-y-6 p-6 bg-slate-50">
          {messages.map((m: ChatMessage, i: number) => {
            const text =
              // be tolerant to any legacy shapes
              (m as any).content ?? (m as any).text ?? (m as any).message ?? "";
            const ts =
              (m as any).timestamp ?? (m as any).ts ?? (m as any).time ?? 0;

            return (
              <div
                key={i}
                className={`flex items-start gap-2 ${
                  m.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                {m.role === "assistant" && (
                  <div className="h-12 w-12 flex items-center justify-center shrink-0 rounded-full bg-emerald-500 text-white font-medium">
                    Agent
                  </div>
                )}

                <div
                  className={`max-w-[75%] rounded-2xl px-4 py-3 relative ${
                    m.role === "user"
                      ? "bg-indigo-100 text-slate-900"
                      : "bg-slate-100 text-slate-900"
                  }`}
                >
                  <div
                    className="prose prose-invert max-w-none"
                    dangerouslySetInnerHTML={{ __html: marked.parse(text) }}
                  />
                  {ts ? (
                    <span className="absolute bottom-1 right-3 text-xs text-slate-300">
                      {formatTime(ts)}
                    </span>
                  ) : null}
                </div>

                {m.role === "user" && (
                  <div className="h-12 w-12 flex items-center justify-center shrink-0 rounded-full bg-indigo-600 text-white font-medium">
                    You
                  </div>
                )}
              </div>
            );
          })}

          {loading && (
            <div className="flex items-center gap-2 text-slate-400 text-sm pl-16">
              <span className="animate-pulse">Agent is typing…</span>
            </div>
          )}
          <div ref={bottomRef} />
        </section>

        {/* Composer */}
        <form onSubmit={onSend} className="border-t border-slate-200 bg-slate-50 p-4">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="How can I help you today?"
            className="w-full h-24 resize-none rounded-xl border border-slate-200 bg-white p-4 text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            disabled={loading}
          />
        </form>
      </div>
    </main>
  );
}
