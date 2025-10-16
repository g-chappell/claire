import { useState } from "react";

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
};

const defaultBase =
  window.location.hostname.endsWith("blacksail.dev")
    ? "https://api.blacksail.dev"
    : "http://localhost:8000";

const API_BASE = (import.meta.env.VITE_API_URL ?? defaultBase).replace(/\/$/, "");

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);

  async function send(userText: string) {
    const trimmed = userText.trim();
    if (!trimmed) return;

    // echo user message
    setMessages((m) => [
      ...m,
      { role: "user", content: trimmed, timestamp: Date.now() },
    ]);

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: trimmed }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const data = await res.json();
      const reply =
        typeof data.reply === "string" ? data.reply : JSON.stringify(data);

      setMessages((m) => [
        ...m,
        { role: "assistant", content: reply, timestamp: Date.now() },
      ]);
    } catch (err: any) {
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: `⚠️ ${err?.message ?? String(err)}`,
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return { messages, send, loading };
}
