// src/api.ts
const defaultBase =
  window.location.hostname.endsWith("blacksail.dev")
    ? "https://api.blacksail.dev"
    : "http://localhost:8000";

export const API_BASE = (import.meta.env.VITE_API_URL ?? defaultBase).replace(/\/$/, "");

export async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${text ? ` – ${text}` : ""}`);
  }
  return res.json() as Promise<T>;
}
