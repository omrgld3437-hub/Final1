import { getAuthToken } from "./session";

export async function apiFetch<T = unknown>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const headers = new Headers(init.headers || {});
  headers.set("X-Requested-With", "XMLHttpRequest");
  const token = getAuthToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const method = (init.method || "GET").toUpperCase();
  if (method !== "GET" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (method !== "GET" && typeof document !== "undefined") {
    const csrf = document.cookie.match(/\bcsrf_token=([^;]+)/);
    if (csrf?.[1]) headers.set("X-CSRF-Token", csrf[1].trim());
  }

  const res = await fetch(path, { ...init, headers, credentials: "include" });
  if (res.status === 401) {
    window.location.replace("/ui/login.html");
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `HTTP ${res.status}`);
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    return (await res.json()) as T;
  }
  return undefined as T;
}

export function apiUrl(path: string, accountId: number, extra?: Record<string, string>): string {
  const q = new URLSearchParams({ account_id: String(accountId) });
  if (extra) {
    Object.entries(extra).forEach(([k, v]) => q.set(k, v));
  }
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}${q.toString()}`;
}
