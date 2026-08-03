import { apiFetch } from "../../lib/api";
import type {
  AccountsResponse,
  AdminChatMessagesResponse,
  AdminChatsResponse,
  AdminMutationResponse,
  CreateAccountPayload,
  CreateAccountResponse,
  CreatePopupPayload,
  ErrorLogCountResponse,
  ErrorLogsResponse,
  PendingRegistrationsResponse,
  PasswordMutationResponse,
  PopupsResponse,
  RegistrationMutationResponse,
  ServerStats,
} from "./types";

export function fetchAccounts(signal?: AbortSignal): Promise<AccountsResponse> {
  return apiFetch<AccountsResponse>("/api/admin/accounts?lite=0", {
    signal,
    dedupe: false,
  });
}

export function fetchAccountSummary(signal?: AbortSignal): Promise<AccountsResponse> {
  return apiFetch<AccountsResponse>("/api/admin/accounts?lite=1", {
    signal,
    dedupe: true,
  });
}

export function createAccount(
  payload: CreateAccountPayload,
): Promise<CreateAccountResponse> {
  return apiFetch<CreateAccountResponse>("/api/admin/accounts", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function generateUserPassword(
  accountId: number,
): Promise<PasswordMutationResponse> {
  return apiFetch<PasswordMutationResponse>(
    "/api/admin/generate-and-set-user-password",
    {
      method: "POST",
      body: JSON.stringify({ account_id: accountId }),
    },
  );
}

export function setUserPassword(
  accountId: number,
  password: string,
  passwordConfirm: string,
): Promise<PasswordMutationResponse> {
  return apiFetch<PasswordMutationResponse>("/api/admin/set-user-password", {
    method: "POST",
    body: JSON.stringify({
      account_id: accountId,
      new_password: password,
      new_password_confirm: passwordConfirm,
    }),
  });
}

export function setUserSuspended(
  userId: number,
  suspend: boolean,
): Promise<AdminMutationResponse> {
  return apiFetch<AdminMutationResponse>("/api/admin/suspend-user", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, suspend }),
  });
}

export function deleteAccount(accountId: number): Promise<AdminMutationResponse> {
  return apiFetch<AdminMutationResponse>(`/api/admin/accounts/${accountId}`, {
    method: "DELETE",
  });
}

export function fetchPendingRegistrations(
  signal?: AbortSignal,
): Promise<PendingRegistrationsResponse> {
  return apiFetch<PendingRegistrationsResponse>("/api/admin/pending-registrations", {
    signal,
    dedupe: false,
  });
}

export function reviewRegistration(
  registrationId: number,
  approve: boolean,
): Promise<RegistrationMutationResponse> {
  return apiFetch<RegistrationMutationResponse>("/api/admin/approve-registration", {
    method: "POST",
    body: JSON.stringify({ registration_id: registrationId, approve }),
  });
}

export function fetchChats(signal?: AbortSignal): Promise<AdminChatsResponse> {
  return apiFetch<AdminChatsResponse>("/api/admin/chats", {
    signal,
    dedupe: false,
  });
}

export function fetchChatMessages(
  userId: number,
  signal?: AbortSignal,
): Promise<AdminChatMessagesResponse> {
  return apiFetch<AdminChatMessagesResponse>(`/api/admin/chats/${userId}/messages`, {
    signal,
    dedupe: false,
  });
}

export function sendChatMessage(
  userId: number,
  message: string,
): Promise<AdminMutationResponse> {
  return apiFetch<AdminMutationResponse>("/api/admin/chats/send", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, message }),
  });
}

export function changeChatState(
  threadId: number,
  action: "lock" | "unlock" | "end" | "reopen" | "clear",
): Promise<AdminMutationResponse> {
  return apiFetch<AdminMutationResponse>(`/api/admin/chats/${threadId}/${action}`, {
    method: "POST",
  });
}

export function fetchServerStats(signal?: AbortSignal): Promise<ServerStats> {
  return apiFetch<ServerStats>("/api/admin/server/stats", {
    signal,
    dedupe: false,
  });
}

export function restartServer(password: string): Promise<AdminMutationResponse> {
  return apiFetch<AdminMutationResponse>("/api/admin/server/restart", {
    method: "POST",
    body: JSON.stringify({ password }),
    timeoutMs: 30_000,
  });
}

export function fetchPopups(signal?: AbortSignal): Promise<PopupsResponse> {
  return apiFetch<PopupsResponse>("/api/admin/popups", {
    signal,
    dedupe: false,
  });
}

export function createPopup(payload: CreatePopupPayload): Promise<AdminMutationResponse> {
  return apiFetch<AdminMutationResponse>("/api/admin/popups", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deletePopup(popupId: number): Promise<AdminMutationResponse> {
  return apiFetch<AdminMutationResponse>(`/api/admin/popups/${popupId}`, {
    method: "DELETE",
  });
}

export function fetchErrorLogs(signal?: AbortSignal): Promise<ErrorLogsResponse> {
  return apiFetch<ErrorLogsResponse>("/api/admin/error-logs?grouped=true&max_unique=100", {
    signal,
    dedupe: false,
  });
}

export function fetchErrorLogCount(signal?: AbortSignal): Promise<ErrorLogCountResponse> {
  return apiFetch<ErrorLogCountResponse>("/api/admin/error-logs/count", {
    signal,
    dedupe: false,
  });
}

export function clearErrorLogs(): Promise<AdminMutationResponse> {
  return apiFetch<AdminMutationResponse>("/api/admin/error-logs", {
    method: "DELETE",
    dedupe: false,
  });
}
