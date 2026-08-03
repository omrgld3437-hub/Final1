const DEFAULT_TIMEOUT_MS = 15_000;

export type ApiErrorKind =
  | "auth"
  | "forbidden"
  | "validation"
  | "rate_limit"
  | "server"
  | "network"
  | "timeout"
  | "duplicate"
  | "unknown";

export class ApiError extends Error {
  readonly status: number;
  readonly kind: ApiErrorKind;
  readonly requestId?: string;
  readonly errorCode?: string;
  readonly retryAfter?: number;
  readonly details?: unknown;

  constructor(
    message: string,
    options: {
      status?: number;
      kind?: ApiErrorKind;
      requestId?: string;
      errorCode?: string;
      retryAfter?: number;
      details?: unknown;
    } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status ?? 0;
    this.kind = options.kind ?? "unknown";
    this.requestId = options.requestId;
    this.errorCode = options.errorCode;
    this.retryAfter = options.retryAfter;
    this.details = options.details;
  }
}

export interface ApiRequestOptions extends RequestInit {
  timeoutMs?: number;
  dedupe?: boolean;
  redirectOnAuthError?: boolean;
}

const inflightGets = new Map<string, Promise<unknown>>();
const inflightMutations = new Set<string>();

function csrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
  return match?.[1] ? decodeURIComponent(match[1].trim()) : null;
}

function errorKind(status: number): ApiErrorKind {
  if (status === 401) return "auth";
  if (status === 403) return "forbidden";
  if (status === 400 || status === 409 || status === 422) return "validation";
  if (status === 429) return "rate_limit";
  if (status >= 500) return "server";
  return "unknown";
}

function readErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const body = payload as Record<string, unknown>;
  const detail = body.detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) =>
        item && typeof item === "object"
          ? String((item as Record<string, unknown>).msg || (item as Record<string, unknown>).message || "")
          : "",
      )
      .filter(Boolean);
    if (messages.length) return messages.join(", ");
  }
  if (typeof detail === "string" && detail.trim()) return detail;
  if (detail && typeof detail === "object") {
    const nested = detail as Record<string, unknown>;
    if (typeof nested.message === "string") return nested.message;
    if (nested.error && typeof nested.error === "object") {
      const error = nested.error as Record<string, unknown>;
      if (typeof error.message === "string") return error.message;
    }
  }
  if (typeof body.message === "string") return body.message;
  if (typeof body.error === "string") return body.error;
  if (body.error && typeof body.error === "object") {
    const nested = body.error as Record<string, unknown>;
    if (typeof nested.message === "string") return nested.message;
  }
  return fallback;
}

function loginRedirect(): void {
  if (typeof window === "undefined") return;
  const current = `${window.location.pathname}${window.location.search}`;
  const next = encodeURIComponent(current);
  window.location.replace(
    `/ui/assets/v2/dashboard/index.html?auth=login&next=${next}`,
  );
}

async function sessionStillValid(): Promise<boolean> {
  if (typeof window === "undefined") return false;
  try {
    const response = await fetch("/api/auth/whoami", {
      method: "GET",
      credentials: "include",
      cache: "no-store",
      headers: {
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest",
      },
    });
    return response.ok;
  } catch {
    // Geçici ağ hatası oturumu yok saymak için yeterli kanıt değildir.
    return true;
  }
}

function requestKey(path: string, init: RequestInit): string {
  const headers = new Headers(init.headers);
  return `${path}|${headers.get("Accept-Language") || ""}`;
}

async function execute<T>(
  path: string,
  options: ApiRequestOptions,
): Promise<T> {
  const {
    timeoutMs = DEFAULT_TIMEOUT_MS,
    dedupe: _dedupe,
    redirectOnAuthError = true,
    ...init
  } = options;
  const method = (init.method || "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  headers.set("X-Requested-With", "XMLHttpRequest");

  if (method !== "GET" && method !== "HEAD") {
    if (init.body != null && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const csrf = csrfToken();
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort("timeout"), timeoutMs);
  const onExternalAbort = () => controller.abort(init.signal?.reason);
  init.signal?.addEventListener("abort", onExternalAbort, { once: true });

  try {
    const response = await fetch(path, {
      ...init,
      method,
      headers,
      signal: controller.signal,
      credentials: "include",
      cache: method === "GET" ? "no-store" : init.cache,
    });
    const contentType = response.headers.get("content-type") || "";
    let payload: unknown;
    if (response.status === 204) {
      payload = undefined;
    } else if (contentType.includes("application/json")) {
      try {
        payload = await response.json();
      } catch (parseError) {
        throw new ApiError(
          method === "GET" || method === "HEAD"
            ? "Sunucu yanıtı doğrulanamadı."
            : "Sunucu yanıtı tamamlanamadı. İşlemin sonucu belirsiz; tekrar göndermeyin.",
          {
            status: response.status,
            kind: method === "GET" || method === "HEAD" ? "server" : "network",
            details: parseError,
          },
        );
      }
    } else {
      payload = await response.text().catch(() => "");
    }
    if (controller.signal.aborted) {
      throw new ApiError(
        method === "GET" || method === "HEAD"
          ? "İstek zaman aşımına uğradı."
          : "Yanıt zaman aşımına uğradı. İşlemin sonucu belirsiz; tekrar göndermeyin.",
        { kind: init.signal?.aborted ? "network" : "timeout" },
      );
    }

    if (!response.ok) {
      const requestId =
        response.headers.get("x-request-id") ||
        (payload && typeof payload === "object"
          ? String(
              (payload as Record<string, unknown>).request_id ||
                ((payload as Record<string, unknown>).meta as Record<string, unknown> | undefined)
                  ?.request_id ||
                "",
            )
          : "") ||
        undefined;
      const message = readErrorMessage(payload, `İstek tamamlanamadı (${response.status})`);
      const body = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
      const detail = body.detail && typeof body.detail === "object" && !Array.isArray(body.detail)
        ? (body.detail as Record<string, unknown>)
        : {};
      const nestedError = body.error && typeof body.error === "object"
        ? (body.error as Record<string, unknown>)
        : {};
      const retryRaw =
        response.headers.get("retry-after") ||
        detail.retry_after ||
        nestedError.retry_after ||
        body.retry_after;
      const error = new ApiError(message, {
        status: response.status,
        kind: errorKind(response.status),
        requestId,
        errorCode: String(
          detail.error_code || nestedError.error_code || body.error_code || "",
        ) || undefined,
        retryAfter: Number.isFinite(Number(retryRaw)) ? Number(retryRaw) : undefined,
        details: payload,
      });
      if (
        response.status === 401 &&
        redirectOnAuthError &&
        path !== "/api/auth/whoami" &&
        !(await sessionStillValid())
      ) {
        loginRedirect();
      }
      throw error;
    }
    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (controller.signal.aborted) {
      throw new ApiError("İstek zaman aşımına uğradı.", {
        kind: init.signal?.aborted ? "network" : "timeout",
      });
    }
    throw new ApiError("Sunucuya ulaşılamadı. Bağlantınızı kontrol edin.", {
      kind: "network",
      details: error,
    });
  } finally {
    window.clearTimeout(timeout);
    init.signal?.removeEventListener("abort", onExternalAbort);
  }
}

export function apiRequest<T = unknown>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const method = (options.method || "GET").toUpperCase();
  const shouldDedupe = method === "GET" && options.dedupe !== false;
  if (!shouldDedupe) {
    if (method === "GET" || method === "HEAD") return execute<T>(path, options);
    const body = typeof options.body === "string" ? options.body : "";
    const mutationKey = `${method}|${path}|${body}`;
    if (inflightMutations.has(mutationKey)) {
      return Promise.reject(
        new ApiError("Bu işlem zaten gönderiliyor.", { kind: "duplicate" }),
      );
    }
    inflightMutations.add(mutationKey);
    return execute<T>(path, options).finally(() => {
      inflightMutations.delete(mutationKey);
    });
  }

  const key = requestKey(path, options);
  const existing = inflightGets.get(key) as Promise<T> | undefined;
  if (existing) return existing;
  const request = execute<T>(path, options).finally(() => inflightGets.delete(key));
  inflightGets.set(key, request);
  return request;
}

export function accountUrl(
  path: string,
  accountId: number,
  params: Record<string, string | number | boolean | undefined> = {},
): string {
  const url = new URL(path, window.location.origin);
  url.searchParams.set("account_id", String(accountId));
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) url.searchParams.set(key, String(value));
  });
  return `${url.pathname}${url.search}`;
}
