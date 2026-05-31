/** Oturum ve hesap çözümlemesi — mevcut dashboard.js ile uyumlu */

export interface SessionUser {
  account_id?: number;
  account_code?: string;
  name?: string;
  surname?: string;
  is_admin?: boolean;
}

export function readStoredUser(): SessionUser | null {
  try {
    const raw = sessionStorage.getItem("user") || localStorage.getItem("user");
    if (!raw) return null;
    return JSON.parse(raw) as SessionUser;
  } catch {
    return null;
  }
}

export function getAuthToken(): string | null {
  return localStorage.getItem("token") || sessionStorage.getItem("token");
}

export function requireAuth(): boolean {
  const token = getAuthToken();
  const user = readStoredUser();
  if (!token || !user) {
    window.location.replace("/ui/login.html");
    return false;
  }
  return true;
}

export async function resolveAccountId(): Promise<{
  accountId: number;
  accountCode: string | null;
  displayName: string;
}> {
  const qs = new URLSearchParams(window.location.search);
  const code = qs.get("account_code");
  const idParam = qs.get("account_id");
  const user = readStoredUser();

  const headers: Record<string, string> = { "X-Requested-With": "XMLHttpRequest" };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  if (code) {
    const res = await fetch(`/api/accounts/by-code/${encodeURIComponent(code)}`, {
      credentials: "include",
      headers,
    });
    if (res.ok) {
      const data = await res.json();
      if (data?.id) {
        return {
          accountId: Number(data.id),
          accountCode: data.account_code || code,
          displayName: formatDisplayName(user),
        };
      }
    }
  }

  if (idParam && /^\d+$/.test(idParam)) {
    return {
      accountId: Number(idParam),
      accountCode: null,
      displayName: formatDisplayName(user),
    };
  }

  const storedId = localStorage.getItem("selectedAccountId") || sessionStorage.getItem("selectedAccountId");
  if (storedId && /^\d+$/.test(storedId)) {
    return {
      accountId: Number(storedId),
      accountCode: localStorage.getItem("selectedAccountCode"),
      displayName: formatDisplayName(user),
    };
  }

  if (user?.account_id != null) {
    return {
      accountId: Number(user.account_id),
      accountCode: user.account_code || null,
      displayName: formatDisplayName(user),
    };
  }

  throw new Error("account_id veya account_code gerekli");
}

function formatDisplayName(user: SessionUser | null, fallback?: string): string {
  if (fallback) return fallback;
  if (!user) return "Kullanıcı";
  const parts = [user.name, user.surname].filter(Boolean).map((s) => String(s).trim());
  return parts.join(" ") || "Kullanıcı";
}

export async function logout(): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const csrf = document.cookie.match(/\bcsrf_token=([^;]+)/);
  if (csrf?.[1]) headers["X-CSRF-Token"] = csrf[1].trim();
  try {
    await fetch("/api/auth/logout", { method: "POST", credentials: "include", headers });
  } catch {
    /* ignore */
  }
  localStorage.removeItem("user");
  localStorage.removeItem("token");
  sessionStorage.removeItem("user");
  sessionStorage.removeItem("token");
  window.location.replace("/ui/login.html");
}
