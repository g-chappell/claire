import { useState } from "react";

export function useChat() {
  const [history, setHistory] = useState<{role: string; text: string}[]>([]);
  const [loading, setLoading] = useState(false);

  async function send(msg: string) {
    setLoading(true);
    setHistory(h => [...h, { role: "user", text: msg }]);

    const r = await fetch(`${import.meta.env.VITE_API_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg })
    }).then(res => res.json());

    setHistory(h => [...h, { role: "assistant", text: r.reply }]);
    setLoading(false);
  }

  return { history, send, loading };
}
