import { useState } from "react";

export interface Msg {
  id: number;
  role: "user" | "assistant";
  text: string;
}

const defaultBase =
  window.location.hostname.endsWith("blacksail.dev")
    ? "https://api.blacksail.dev"
    : "http://localhost:8000";

const API_BASE = (import.meta.env.VITE_API_URL ?? defaultBase).replace(/\/$/, "");

export function useChat() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [loading, setLoading] = useState(false);

  async function send(userText: string) {
    if (!userText.trim()) return;
    const id = Date.now();
    setMessages((m) => [...m, { id, role: "user", text: userText }]);
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userText }),
      });
      const data = await res.json();
      setMessages((m) => [...m, { id: id + 1, role: "assistant", text: data.reply }]);
    } catch (err) {
      setMessages((m) => [...m, { id: id + 1, role: "assistant", text: String(err) }]);
    } finally {
      setLoading(false);
    }
  }

  return { messages, send, loading };
}
