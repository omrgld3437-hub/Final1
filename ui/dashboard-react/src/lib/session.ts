import { apiRequest } from "../core/api/http";

/** Cookie-first session and account scope resolution. */

export interface SessionUser {
  user_id?: number;
  account_id?: number;
  account_code?: string;
  name?: string;
  surname?: string;
  is_admin?: boolean;
}

interface AdminVisibleAccount {
  account_id?: number;
  account_code?: string | null;
  admin_isolated?: boolean;
  name?: string;
  user_name?: string | null;
  user_surname?: string | null;
  user_username?: string | null;
}

async function assertAdminAccountVisible(accountId: number): Promise<AdminVisibleAccount | null> {
  const response = await apiRequest<{
    accounts?: AdminVisibleAccount[];
  }>("/api/admin/accounts?lite=1", {
    timeoutMs: 10_000,
    dedupe: true,
    redirectOnAuthError: false,
  });
  const account = response.accounts?.find(
    (item) => Number(item.account_id) === accountId,
  );
  if (account?.admin_isolated) {
    throw new Error("Bu hesap sahibi yönetici görünümünü kapattı.");
  }
  return account || null;
}

function accountDisplayName(account: AdminVisibleAccount | null): string {
  if (!account) return "Hesap";
  const fullName = [account.user_name, account.user_surname]
    .filter(Boolean)
    .map((value) => String(value).trim())
    .join(" ");
  return fullName || account.name || account.user_username || account.account_code || "Hesap";
}

export async function resolveAccountId(): Promise<{
  accountId: number;
  accountCode: string | null;
  displayName: string;
  isAdmin: boolean;
}> {
  const qs = new URLSearchParams(window.location.search);
  const code = qs.get("account_code");
  const idParam = qs.get("account_id");
  const identity = await apiRequest<SessionUser>("/api/auth/whoami", {
    timeoutMs: 10_000,
    dedupe: true,
    redirectOnAuthError: false,
  });
  // The V2 runtime is cookie-only. Remove legacy bearer copies after the
  // HttpOnly session cookie has been verified by whoami.
  localStorage.removeItem("token");
  sessionStorage.removeItem("token");
  const user = identity;

  if (code && user.is_admin) {
    const data = await apiRequest<{ id?: number; account_code?: string }>(
      `/api/accounts/by-code/${encodeURIComponent(code)}`,
      { timeoutMs: 10_000 },
    );
    if (data?.id) {
      const selectedAccount = await assertAdminAccountVisible(Number(data.id));
      return {
        accountId: Number(data.id),
        accountCode: data.account_code || code,
        displayName: accountDisplayName(selectedAccount),
        isAdmin: Boolean(user.is_admin),
      };
    }
  }

  if (idParam && /^\d+$/.test(idParam) && user.is_admin) {
    const selectedAccount = await assertAdminAccountVisible(Number(idParam));
    return {
      accountId: Number(idParam),
      accountCode: null,
      displayName: accountDisplayName(selectedAccount),
      isAdmin: true,
    };
  }

  if (user?.account_id != null) {
    return {
      accountId: Number(user.account_id),
      accountCode: user.account_code || null,
      displayName: formatDisplayName(user),
      isAdmin: Boolean(user.is_admin),
    };
  }

  if (user.is_admin) {
    return {
      accountId: 0,
      accountCode: null,
      displayName: formatDisplayName(user, "Yönetici"),
      isAdmin: true,
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

export async function logout(accountId: number): Promise<void> {
  const response = await apiRequest<{ success?: boolean }>("/api/auth/logout", {
    method: "POST",
    body: JSON.stringify({ account_id: accountId }),
    redirectOnAuthError: false,
    dedupe: false,
  });
  if (!response?.success) {
    throw new Error("Sunucu oturumu kapattığını doğrulamadı.");
  }
  localStorage.removeItem("user");
  localStorage.removeItem("token");
  sessionStorage.removeItem("user");
  sessionStorage.removeItem("token");
  sessionStorage.removeItem("v2_must_change_password");
  sessionStorage.removeItem("v2_first_login");
  try {
    const channel = new BroadcastChannel("ayserose-session");
    channel.postMessage({ type: "logout", at: Date.now() });
    channel.close();
  } catch {
    /* BroadcastChannel is optional. */
  }
  window.location.replace("/ui/assets/v2/dashboard/index.html?auth=login");
}
