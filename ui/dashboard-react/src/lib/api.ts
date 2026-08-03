import { accountUrl, apiRequest } from "../core/api/http";
import type { ApiRequestOptions } from "../core/api/http";

/** Compatibility export while feature views move to the V2 core API. */
export function apiFetch<T = unknown>(
  path: string,
  init: ApiRequestOptions = {},
): Promise<T> {
  return apiRequest<T>(path, init);
}

export function apiUrl(
  path: string,
  accountId: number,
  extra?: Record<string, string>,
): string {
  return accountUrl(path, accountId, extra);
}

export { ApiError } from "../core/api/http";
