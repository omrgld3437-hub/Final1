import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Activity,
  AlertTriangle,
  BellRing,
  Check,
  ChevronRight,
  CircleGauge,
  Copy,
  Database,
  FileWarning,
  Inbox,
  KeyRound,
  LayoutDashboard,
  LoaderCircle,
  LockKeyhole,
  LogOut,
  MessageSquare,
  Network,
  Power,
  RefreshCw,
  Search,
  Send,
  Server,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  UnlockKeyhole,
  UserCheck,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useDashboard } from "../../context/DashboardContext";
import {
  changeChatState,
  clearErrorLogs,
  createAccount,
  createPopup as publishPopup,
  deleteAccount,
  deletePopup,
  fetchAccounts,
  fetchAccountSummary,
  fetchChatMessages,
  fetchChats,
  fetchErrorLogCount,
  fetchErrorLogs,
  fetchPendingRegistrations,
  fetchPopups,
  fetchServerStats,
  generateUserPassword,
  restartServer,
  reviewRegistration,
  sendChatMessage,
  setUserPassword,
  setUserSuspended,
} from "./api";
import type {
  AdminAccount,
  AdminChat,
  AdminChatMessagesResponse,
  AdminPopup,
  AdminTab,
  CreateAccountPayload,
  CreateAccountResponse,
  CreatePopupPayload,
  PasswordMutationResponse,
  ResourceState,
} from "./types";

const CHAT_MAX_LENGTH = 2000;

const TAB_DEFINITIONS: Array<{
  key: AdminTab;
  label: string;
  icon: LucideIcon;
}> = [
  { key: "overview", label: "Operasyon Özeti", icon: LayoutDashboard },
  { key: "accounts", label: "Hesaplar", icon: Users },
  { key: "chats", label: "Sohbetler", icon: MessageSquare },
  { key: "server", label: "Sunucu", icon: Server },
  { key: "popups", label: "Pop-up", icon: BellRing },
  { key: "errors", label: "Hata Logları", icon: FileWarning },
];

const INITIAL_CHAT_DETAIL: ResourceState<AdminChatMessagesResponse> = {
  data: null,
  loading: false,
  error: "",
  updatedAt: null,
};

function initialResource<T>(): ResourceState<T> {
  return { data: null, loading: false, error: "", updatedAt: null };
}

function useAdminResource<T>(loader: (signal?: AbortSignal) => Promise<T>) {
  const [state, setState] = useState<ResourceState<T>>(initialResource);
  const requestRef = useRef<AbortController | null>(null);

  const load = useCallback(
    async (silent = false) => {
      requestRef.current?.abort();
      const controller = new AbortController();
      requestRef.current = controller;
      setState((current) => ({
        ...current,
        loading: silent ? current.loading : true,
        error: silent ? current.error : "",
      }));
      try {
        const data = await loader(controller.signal);
        if (controller.signal.aborted) return;
        setState({ data, loading: false, error: "", updatedAt: new Date() });
      } catch (error) {
        if (controller.signal.aborted) return;
        setState((current) => ({
          ...current,
          loading: false,
          error: error instanceof Error ? error.message : "Veri yüklenemedi.",
        }));
      } finally {
        if (requestRef.current === controller) requestRef.current = null;
      }
    },
    [loader],
  );

  useEffect(
    () => () => {
      requestRef.current?.abort();
    },
    [],
  );

  return { state, load };
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("tr-TR", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "Europe/Istanbul",
  });
}

function formatUsd(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });
}

function formatNumber(value: number | null | undefined, fractionDigits = 0): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toLocaleString("tr-TR", {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  });
}

function defaultPopupExpiry(): string {
  const date = new Date();
  date.setDate(date.getDate() + 7);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function LoadingBlock({ label = "Veriler yükleniyor…" }: { label?: string }) {
  return (
    <div className="grid min-h-44 place-items-center rounded-2xl border border-neutral-800 bg-neutral-900/70">
      <div className="flex items-center gap-2 text-sm font-semibold text-neutral-400">
        <LoaderCircle className="h-4 w-4 animate-spin text-[#f0b90b]" />
        {label}
      </div>
    </div>
  );
}

function ErrorBlock({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div
      className="rounded-2xl border border-[#f6465d]/25 bg-[#f6465d]/10 p-5"
      role="alert"
    >
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-[#f6465d]" />
        <div className="min-w-0">
          <p className="font-bold text-[#f6465d]">Veri alınamadı</p>
          <p className="mt-1 break-words text-sm text-neutral-300">{message}</p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-4 rounded-lg border border-[#f6465d]/30 px-3 py-2 text-xs font-bold text-[#f6465d] transition hover:bg-[#f6465d]/10"
          >
            Yeniden dene
          </button>
        </div>
      </div>
    </div>
  );
}

function EmptyBlock({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="grid min-h-44 place-items-center rounded-2xl border border-dashed border-neutral-800 bg-neutral-900/40 p-6 text-center">
      <div>
        <Inbox className="mx-auto h-7 w-7 text-neutral-600" />
        <p className="mt-3 font-bold text-neutral-200">{title}</p>
        <p className="mt-1 text-sm text-neutral-500">{description}</p>
      </div>
    </div>
  );
}

function RefreshWarning({ message }: { message: string }) {
  return (
    <div
      className="mb-4 flex items-start gap-2 rounded-xl border border-[#f0b90b]/20 bg-[#f0b90b]/10 px-3 py-2.5 text-xs text-[#f0b90b]"
      role="status"
    >
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>Son yenileme tamamlanamadı; ekranda önceki başarılı veri gösteriliyor. {message}</span>
    </div>
  );
}

function SectionHeader({
  title,
  description,
  updatedAt,
  loading,
  onRefresh,
  actions,
}: {
  title: string;
  description: string;
  updatedAt?: Date | null;
  loading?: boolean;
  onRefresh?: () => void;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
      <div>
        <h2 className="text-xl font-black tracking-tight text-white">{title}</h2>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-neutral-400">{description}</p>
        {updatedAt && (
          <p className="mt-1 text-[11px] text-neutral-600">
            Son güncelleme: {updatedAt.toLocaleTimeString("tr-TR")}
          </p>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {actions}
        {onRefresh && (
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-xl border border-neutral-700 bg-neutral-900 px-3.5 py-2.5 text-xs font-bold text-neutral-300 transition hover:border-neutral-600 hover:text-white disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Yenile
          </button>
        )}
      </div>
    </div>
  );
}

function StatusBadge({
  tone,
  children,
}: {
  tone: "green" | "red" | "amber" | "neutral";
  children: React.ReactNode;
}) {
  const classes = {
    green: "border-[#0ecb81]/20 bg-[#0ecb81]/10 text-[#0ecb81]",
    red: "border-[#f6465d]/20 bg-[#f6465d]/10 text-[#f6465d]",
    amber: "border-[#f0b90b]/20 bg-[#f0b90b]/10 text-[#f0b90b]",
    neutral: "border-neutral-700 bg-neutral-800 text-neutral-300",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-1 text-[10px] font-black uppercase tracking-wider ${classes[tone]}`}
    >
      {children}
    </span>
  );
}

function SummaryCard({
  icon: Icon,
  label,
  value,
  detail,
  loading,
  error,
  tone = "amber",
}: {
  icon: LucideIcon;
  label: string;
  value: React.ReactNode;
  detail: string;
  loading?: boolean;
  error?: string;
  tone?: "amber" | "green" | "red";
}) {
  const iconClass = {
    amber: "bg-[#f0b90b]/10 text-[#f0b90b]",
    green: "bg-[#0ecb81]/10 text-[#0ecb81]",
    red: "bg-[#f6465d]/10 text-[#f6465d]",
  }[tone];
  return (
    <div className="rounded-2xl border border-neutral-800 bg-neutral-900/80 p-5 shadow-lg shadow-black/10">
      <div className="flex items-start justify-between gap-3">
        <div className={`grid h-10 w-10 place-items-center rounded-xl ${iconClass}`}>
          <Icon className="h-5 w-5" />
        </div>
        {error && <AlertTriangle className="h-4 w-4 text-[#f6465d]" title={error} />}
      </div>
      <p className="mt-5 text-xs font-bold uppercase tracking-widest text-neutral-500">{label}</p>
      {loading ? (
        <div className="mt-2 h-8 w-20 animate-pulse rounded bg-neutral-800" />
      ) : (
        <p className="mt-1 text-2xl font-black text-white">{error ? "—" : value}</p>
      )}
      <p className="mt-2 text-xs text-neutral-500">{error || detail}</p>
    </div>
  );
}

function confirmIrreversible(firstMessage: string, finalMessage: string): boolean {
  return window.confirm(firstMessage) && window.confirm(finalMessage);
}

function AdminDialog({
  title,
  description,
  onClose,
  children,
}: {
  title: string;
  description?: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-[100] flex items-end justify-center bg-black/75 p-3 backdrop-blur-sm sm:items-center sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section className="max-h-[calc(100dvh-1.5rem)] w-full max-w-xl overflow-y-auto rounded-3xl border border-neutral-700 bg-[#181a20] shadow-2xl shadow-black/60">
        <header className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-neutral-800 bg-[#181a20]/95 px-5 py-4 backdrop-blur sm:px-6">
          <div>
            <h2 className="text-lg font-black text-white">{title}</h2>
            {description && <p className="mt-1 text-xs leading-5 text-neutral-500">{description}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-neutral-700 text-neutral-400 transition hover:bg-neutral-800 hover:text-white"
            aria-label="Pencereyi kapat"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="p-5 sm:p-6">{children}</div>
      </section>
    </div>
  );
}

export default function AdminPage({
  onOpenAccount,
}: {
  onOpenAccount?: (accountId: number) => void;
}) {
  const { isAdmin, displayName, logout } = useDashboard();
  const [activeTab, setActiveTab] = useState<AdminTab>("overview");
  const [notice, setNotice] = useState("");
  const [actionError, setActionError] = useState("");
  const mutationLocksRef = useRef(new Set<string>());
  const [pendingActions, setPendingActions] = useState<Set<string>>(() => new Set());

  const accounts = useAdminResource(fetchAccounts);
  const accountSummary = useAdminResource(fetchAccountSummary);
  const registrations = useAdminResource(fetchPendingRegistrations);
  const chats = useAdminResource(fetchChats);
  const serverStats = useAdminResource(fetchServerStats);
  const popups = useAdminResource(fetchPopups);
  const errorLogs = useAdminResource(fetchErrorLogs);
  const errorCount = useAdminResource(fetchErrorLogCount);

  const {
    load: loadAccounts,
    state: accountsState,
  } = accounts;
  const {
    load: loadAccountSummary,
    state: accountSummaryState,
  } = accountSummary;
  const {
    load: loadRegistrations,
    state: registrationsState,
  } = registrations;
  const { load: loadChats, state: chatsState } = chats;
  const { load: loadServerStats, state: serverStatsState } = serverStats;
  const { load: loadPopups, state: popupsState } = popups;
  const { load: loadErrorLogs, state: errorLogsState } = errorLogs;
  const { load: loadErrorCount, state: errorCountState } = errorCount;

  const runMutation = useCallback(
    async <T,>(key: string, action: () => Promise<T>): Promise<T | null> => {
      if (mutationLocksRef.current.has(key)) return null;
      mutationLocksRef.current.add(key);
      setPendingActions((current) => new Set(current).add(key));
      setNotice("");
      setActionError("");
      try {
        return await action();
      } catch (error) {
        setActionError(error instanceof Error ? error.message : "İşlem tamamlanamadı.");
        return null;
      } finally {
        mutationLocksRef.current.delete(key);
        setPendingActions((current) => {
          const next = new Set(current);
          next.delete(key);
          return next;
        });
      }
    },
    [],
  );

  const isPending = (key: string) => pendingActions.has(key);

  useEffect(() => {
    if (!isAdmin) return;
    void loadAccountSummary();
    void loadServerStats();
    void loadPopups();
    void loadErrorCount();
  }, [
    isAdmin,
    loadAccountSummary,
    loadErrorCount,
    loadPopups,
    loadServerStats,
  ]);

  useEffect(() => {
    if (
      !isAdmin ||
      activeTab !== "accounts" ||
      accountsState.data ||
      accountsState.loading
    ) {
      return;
    }
    void loadAccounts();
  }, [
    activeTab,
    accountsState.data,
    accountsState.loading,
    isAdmin,
    loadAccounts,
  ]);

  useEffect(() => {
    if (!isAdmin || activeTab !== "chats" || chatsState.data || chatsState.loading) {
      return;
    }
    void loadChats();
  }, [activeTab, chatsState.data, chatsState.loading, isAdmin, loadChats]);

  useEffect(() => {
    if (!isAdmin || activeTab !== "errors" || errorLogsState.data || errorLogsState.loading) {
      return;
    }
    void loadErrorLogs();
  }, [activeTab, errorLogsState.data, errorLogsState.loading, isAdmin, loadErrorLogs]);

  useEffect(() => {
    if (!isAdmin) return;
    const refreshIfVisible = () => {
      if (document.visibilityState === "visible") void loadServerStats(true);
    };
    const interval = window.setInterval(refreshIfVisible, 30_000);
    const handleVisibility = () => {
      if (document.visibilityState === "visible") refreshIfVisible();
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [isAdmin, loadServerStats]);

  if (!isAdmin) {
    return (
      <main className="grid min-h-[70vh] place-items-center p-6">
        <section className="max-w-md rounded-3xl border border-[#f6465d]/25 bg-neutral-900 p-8 text-center shadow-2xl">
          <ShieldAlert className="mx-auto h-10 w-10 text-[#f6465d]" />
          <h1 className="mt-4 text-xl font-black text-white">Yetkisiz alan</h1>
          <p className="mt-2 text-sm leading-6 text-neutral-400">
            Bu görünüm yalnızca doğrulanmış yönetici oturumlarına açıktır.
          </p>
        </section>
      </main>
    );
  }

  const totalUnread = (chatsState.data?.chats || []).reduce(
    (sum, chat) => sum + Number(chat.unread_count || 0),
    0,
  );
  const activePopupCount = (popupsState.data?.popups || []).filter(
    (popup) => popup.is_active,
  ).length;

  return (
    <main className="min-h-screen bg-[#111216] text-neutral-200">
      <div className="mx-auto max-w-[1500px] px-4 py-6 sm:px-6 lg:px-8">
        <header className="mb-6 rounded-3xl border border-neutral-800 bg-[radial-gradient(circle_at_top_right,rgba(240,185,11,0.12),transparent_35%),#181a20] p-6 shadow-2xl shadow-black/20 sm:p-8">
          <div className="flex flex-col justify-between gap-5 lg:flex-row lg:items-center">
            <div>
              <div className="flex items-center gap-2 text-xs font-black uppercase tracking-[0.2em] text-[#f0b90b]">
                <ShieldCheck className="h-4 w-4" />
                Yönetici çalışma alanı
              </div>
              <h1 className="mt-3 text-3xl font-black tracking-tight text-white">
                Operasyon Kontrol Merkezi
              </h1>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge tone={serverStatsState.data?.lockdown ? "red" : "green"}>
                {serverStatsState.data?.lockdown ? "Erişim kilitli" : "Sistem erişilebilir"}
              </StatusBadge>
              <StatusBadge tone="neutral">
                {serverStatsState.data?.uptime_formatted
                  ? `Çalışma: ${serverStatsState.data.uptime_formatted}`
                  : "Sunucu durumu bekleniyor"}
              </StatusBadge>
              <button
                type="button"
                onClick={logout}
                className="inline-flex items-center gap-2 rounded-xl border border-neutral-700 bg-neutral-900 px-3.5 py-2.5 text-xs font-black text-neutral-300 transition hover:border-neutral-600 hover:text-white"
              >
                <LogOut className="h-4 w-4" />
                Çıkış
              </button>
            </div>
          </div>
        </header>

        <nav
          className="mb-6 flex gap-2 overflow-x-auto rounded-2xl border border-neutral-800 bg-[#181a20] p-2"
          aria-label="Yönetim bölümleri"
        >
          {TAB_DEFINITIONS.map(({ key, label, icon: Icon }) => {
            const badge =
              key === "chats"
                  ? totalUnread
                  : key === "errors"
                    ? errorCountState.data?.count
                    : undefined;
            return (
              <button
                type="button"
                key={key}
                onClick={() => {
                  setActiveTab(key);
                  setActionError("");
                  setNotice("");
                }}
                className={`relative inline-flex shrink-0 items-center gap-2 rounded-xl px-4 py-3 text-xs font-black transition ${
                  activeTab === key
                    ? "bg-[#f0b90b] text-neutral-950 shadow-lg shadow-[#f0b90b]/10"
                    : "text-neutral-400 hover:bg-neutral-800 hover:text-white"
                }`}
                aria-current={activeTab === key ? "page" : undefined}
              >
                <Icon className="h-4 w-4" />
                {label}
                {badge != null && badge > 0 && (
                  <span
                    className={`min-w-5 rounded-full px-1.5 py-0.5 text-[9px] ${
                      activeTab === key
                        ? "bg-neutral-950 text-[#f0b90b]"
                        : "bg-[#f6465d] text-white"
                    }`}
                  >
                    {badge > 999 ? "999+" : badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {actionError && (
          <div
            className="mb-5 flex items-start gap-3 rounded-2xl border border-[#f6465d]/25 bg-[#f6465d]/10 px-4 py-3 text-sm text-[#f6465d]"
            role="alert"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span className="min-w-0 flex-1 break-words">{actionError}</span>
            <button
              type="button"
              onClick={() => setActionError("")}
              aria-label="Hata mesajını kapat"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}
        {notice && (
          <div
            className="mb-5 flex items-start gap-3 rounded-2xl border border-[#0ecb81]/20 bg-[#0ecb81]/10 px-4 py-3 text-sm text-[#0ecb81]"
            role="status"
          >
            <Check className="mt-0.5 h-4 w-4 shrink-0" />
            <span className="min-w-0 flex-1 break-words">{notice}</span>
            <button
              type="button"
              onClick={() => setNotice("")}
              aria-label="Bilgi mesajını kapat"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {activeTab === "overview" && (
          <OverviewTab
            accountsState={accountsState.data ? accountsState : accountSummaryState}
            registrationsState={registrationsState}
            chatsState={chatsState}
            serverStatsState={serverStatsState}
            popupsState={popupsState}
            errorCountState={errorCountState}
            totalUnread={totalUnread}
            activePopupCount={activePopupCount}
            onNavigate={setActiveTab}
          />
        )}

        {activeTab === "accounts" && (
          <AccountsTab
            state={accountsState}
            onRefresh={() => void loadAccounts()}
            isPending={isPending}
            onOpenAccount={onOpenAccount}
            onCreate={async (payload) => {
              const result = await runMutation("account-create", () =>
                createAccount(payload),
              );
              if (!result) return null;
              setNotice(`${result.name} hesabı oluşturuldu.`);
              await Promise.all([loadAccounts(), loadAccountSummary()]);
              return result;
            }}
            onGeneratePassword={async (account) => {
              const result = await runMutation(
                `account-password-generate-${account.account_id}`,
                () => generateUserPassword(account.account_id),
              );
              if (!result) return null;
              setNotice(result.message || "Tek kullanımlık şifre oluşturuldu.");
              return result;
            }}
            onSetPassword={async (account, password, passwordConfirm) => {
              const result = await runMutation(
                `account-password-set-${account.account_id}`,
                () => setUserPassword(account.account_id, password, passwordConfirm),
              );
              if (!result) return false;
              setNotice(result.message || "Hesap şifresi güncellendi.");
              return true;
            }}
            onUnsuspend={async (account) => {
              if (!account.user_id) return false;
              const result = await runMutation(
                `account-unsuspend-${account.account_id}`,
                () => setUserSuspended(account.user_id!, false),
              );
              if (!result) return false;
              setNotice(result.message || "Hesap askıdan çıkarıldı.");
              await Promise.all([loadAccounts(), loadAccountSummary()]);
              return true;
            }}
            onDelete={async (account) => {
              const label = account.account_code || `#${account.account_id}`;
              if (
                !confirmIrreversible(
                  `${label} hesabı silinecek. Hesapta bot varsa backend işlemi güvenle reddeder. Devam edilsin mi?`,
                  `SON ONAY: ${label} hesabı ve ilişkili verileri için silme isteği gönderilsin mi?`,
                )
              ) {
                return;
              }
              const result = await runMutation(`account-delete-${account.account_id}`, () =>
                deleteAccount(account.account_id),
              );
              if (!result) return;
              setNotice(result.message || `${label} hesabı silindi.`);
              await Promise.all([loadAccounts(), loadAccountSummary()]);
              return true;
            }}
          />
        )}

        {activeTab === "chats" && (
          <ChatsTab
            state={chatsState}
            onRefresh={() => void loadChats()}
            isPending={isPending}
            runMutation={runMutation}
            onDataChanged={loadChats}
            setNotice={setNotice}
            setActionError={setActionError}
          />
        )}

        {activeTab === "server" && (
          <ServerTab
            state={serverStatsState}
            onRefresh={() => void loadServerStats()}
            isPending={isPending}
            onRestart={async () => {
              const password = window.prompt(
                "Sunucuyu yeniden başlatmak için admin şifrenizi girin:",
              );
              if (!password?.trim()) return;
              if (
                !confirmIrreversible(
                  "Sunucu yeniden başlatılırken bağlantılar kısa süreli kesilebilir.",
                  "SON ONAY: Sunucu şimdi yeniden başlatılsın mı?",
                )
              ) {
                return;
              }
              const result = await runMutation("server-restart", () =>
                restartServer(password.trim()),
              );
              if (!result) return;
              setNotice(result.message || "Sunucu yeniden başlatılıyor.");
            }}
          />
        )}

        {activeTab === "popups" && (
          <PopupsTab
            state={popupsState}
            onRefresh={() => void loadPopups()}
            isPending={isPending}
            onCreate={async (payload) => {
              const result = await runMutation("popup-create", () => publishPopup(payload));
              if (!result) return false;
              setNotice(result.message || "Pop-up yayınlandı.");
              await loadPopups();
              return true;
            }}
            onDelete={async (popup) => {
              if (
                !confirmIrreversible(
                  "Bu pop-up yayından kaldırılacak ve kullanıcılar artık göremeyecek.",
                  `SON ONAY: #${popup.id} pop-up kalıcı olarak kaldırılsın mı?`,
                )
              ) {
                return;
              }
              const result = await runMutation(`popup-delete-${popup.id}`, () =>
                deletePopup(popup.id),
              );
              if (!result) return;
              setNotice(result.message || "Pop-up kaldırıldı.");
              await loadPopups();
            }}
          />
        )}

        {activeTab === "errors" && (
          <ErrorsTab
            state={errorLogsState}
            count={errorCountState.data?.count ?? null}
            onRefresh={async () => {
              await Promise.all([loadErrorLogs(), loadErrorCount()]);
            }}
            clearing={isPending("errors-clear")}
            onClear={async () => {
              if (!confirmIrreversible(
                "Kayıtlı hata logları sıfırlanacak. Bu işlem çalışan botları veya kullanıcı verilerini etkilemez.",
                "SON ONAY: Hata kayıtları şimdi temizlensin mi?",
              )) return;
              const result = await runMutation("errors-clear", clearErrorLogs);
              if (!result) return;
              setNotice(result.message || `${result.deleted || 0} hata kaydı temizlendi.`);
              await Promise.all([loadErrorLogs(), loadErrorCount()]);
            }}
          />
        )}
      </div>
    </main>
  );
}

function OverviewTab({
  accountsState,
  registrationsState,
  chatsState,
  serverStatsState,
  popupsState,
  errorCountState,
  totalUnread,
  activePopupCount,
  onNavigate,
}: {
  accountsState: ResourceState<Awaited<ReturnType<typeof fetchAccounts>>>;
  registrationsState: ResourceState<Awaited<ReturnType<typeof fetchPendingRegistrations>>>;
  chatsState: ResourceState<Awaited<ReturnType<typeof fetchChats>>>;
  serverStatsState: ResourceState<Awaited<ReturnType<typeof fetchServerStats>>>;
  popupsState: ResourceState<Awaited<ReturnType<typeof fetchPopups>>>;
  errorCountState: ResourceState<Awaited<ReturnType<typeof fetchErrorLogCount>>>;
  totalUnread: number;
  activePopupCount: number;
  onNavigate: (tab: AdminTab) => void;
}) {
  const resources = [
    accountsState,
    registrationsState,
    chatsState,
    serverStatsState,
    popupsState,
    errorCountState,
  ];
  const readyCount = resources.filter((resource) => resource.data && !resource.error).length;
  const failedCount = resources.filter((resource) => resource.error).length;

  return (
    <section>
      <SectionHeader
        title="Operasyon özeti"
        description="Salt okunur başlangıç ekranı. Kritik iş yükü, kullanıcı talepleri ve sunucu sağlığı tek bakışta görünür."
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <SummaryCard
          icon={Users}
          label="Aktif hesaplar"
          value={accountsState.data?.totals.total_accounts ?? "—"}
          detail={`${accountsState.data?.totals.total_active_bots ?? 0} aktif bot`}
          loading={accountsState.loading && !accountsState.data}
          error={accountsState.error}
        />
        <SummaryCard
          icon={CircleGauge}
          label="Sunucu CPU"
          value={
            serverStatsState.data?.cpu_percent == null
              ? "—"
              : `%${formatNumber(serverStatsState.data.cpu_percent, 1)}`
          }
          detail={
            serverStatsState.data?.uptime_formatted
              ? `${serverStatsState.data.uptime_formatted} kesintisiz çalışma`
              : "Sunucu ölçümü bekleniyor"
          }
          loading={serverStatsState.loading && !serverStatsState.data}
          error={serverStatsState.error}
          tone={serverStatsState.data?.lockdown ? "red" : "green"}
        />
        <SummaryCard
          icon={BellRing}
          label="Aktif pop-up"
          value={popupsState.data ? activePopupCount : "—"}
          detail={`${popupsState.data?.popups.length ?? 0} toplam yayın kaydı`}
          loading={popupsState.loading && !popupsState.data}
          error={popupsState.error}
        />
        <SummaryCard
          icon={FileWarning}
          label="Hata kayıtları"
          value={errorCountState.data?.count ?? "—"}
          detail="Gruplanmamış toplam hata kaydı"
          loading={errorCountState.loading && !errorCountState.data}
          error={errorCountState.error}
          tone={errorCountState.data?.count ? "red" : "green"}
        />
      </div>

      <div className="mt-6 hidden gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-2xl border border-neutral-800 bg-neutral-900/80 p-5">
          <div className="flex items-center gap-3">
            <div
              className={`grid h-10 w-10 place-items-center rounded-xl ${
                failedCount ? "bg-[#f6465d]/10" : "bg-[#0ecb81]/10"
              }`}
            >
              {failedCount ? (
                <AlertTriangle className="h-5 w-5 text-[#f6465d]" />
              ) : (
                <Activity className="h-5 w-5 text-[#0ecb81]" />
              )}
            </div>
            <div>
              <h3 className="font-black text-white">Veri kaynağı sağlığı</h3>
              <p className="text-xs text-neutral-500">
                {readyCount}/6 operasyon kaynağı güncel, {failedCount} kaynakta hata var.
              </p>
            </div>
          </div>
          <div className="mt-5 h-2 overflow-hidden rounded-full bg-neutral-800">
            <div
              className={`h-full rounded-full ${failedCount ? "bg-[#f0b90b]" : "bg-[#0ecb81]"}`}
              style={{ width: `${(readyCount / 6) * 100}%` }}
            />
          </div>
        </div>

        <div className="rounded-2xl border border-neutral-800 bg-neutral-900/80 p-5">
          <h3 className="font-black text-white">Hızlı inceleme</h3>
          <div className="mt-3 grid grid-cols-2 gap-2">
            {(
              [
                ["registrations", "Kayıt talepleri"],
                ["chats", "Sohbet kutusu"],
                ["server", "Sunucu sağlığı"],
                ["errors", "Hata analizi"],
              ] as Array<[AdminTab, string]>
            ).map(([tab, label]) => (
              <button
                type="button"
                key={tab}
                onClick={() => onNavigate(tab)}
                className="flex items-center justify-between rounded-xl border border-neutral-800 bg-[#181a20] px-3 py-2.5 text-left text-xs font-bold text-neutral-300 transition hover:border-neutral-700 hover:text-white"
              >
                {label}
                <ChevronRight className="h-3.5 w-3.5 text-neutral-600" />
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

const adminInputClass =
  "w-full rounded-xl border border-neutral-700 bg-[#111216] px-3.5 py-3 text-sm text-white outline-none transition placeholder:text-neutral-600 focus:border-[#f0b90b]";

function AdminField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-black text-neutral-300">{label}</span>
      {children}
    </label>
  );
}

function CredentialPanel({
  username,
  password,
}: {
  username?: string;
  password: string;
}) {
  const [copied, setCopied] = useState(false);
  const copyValue = username ? `Kullanıcı adı: ${username}\nŞifre: ${password}` : password;
  return (
    <div className="rounded-2xl border border-[#0ecb81]/25 bg-[#0ecb81]/5 p-4">
      <div className="flex items-center gap-2 text-[#0ecb81]">
        <Check className="h-4 w-4" />
        <strong className="text-sm">Giriş bilgileri hazır</strong>
      </div>
      <p className="mt-2 text-xs leading-5 text-neutral-400">
        Bu bilgi yalnızca şimdi gösterilir. Güvenli biçimde kullanıcıyla paylaşın.
      </p>
      {username && (
        <div className="mt-3 rounded-xl bg-black/30 px-3 py-2">
          <span className="block text-[10px] uppercase tracking-widest text-neutral-600">
            Kullanıcı adı
          </span>
          <code className="mt-1 block break-all text-sm font-bold text-white">{username}</code>
        </div>
      )}
      <div className="mt-2 rounded-xl bg-black/30 px-3 py-2">
        <span className="block text-[10px] uppercase tracking-widest text-neutral-600">
          Tek kullanımlık şifre
        </span>
        <code className="mt-1 block break-all text-sm font-bold text-white">{password}</code>
      </div>
      <button
        type="button"
        onClick={async () => {
          await navigator.clipboard.writeText(copyValue);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1600);
        }}
        className="mt-3 inline-flex items-center gap-2 rounded-xl border border-[#0ecb81]/25 px-3 py-2 text-xs font-black text-[#0ecb81]"
      >
        {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
        {copied ? "Kopyalandı" : "Bilgileri kopyala"}
      </button>
    </div>
  );
}

function AccountsTab({
  state,
  onRefresh,
  isPending,
  onOpenAccount,
  onCreate,
  onGeneratePassword,
  onSetPassword,
  onUnsuspend,
  onDelete,
}: {
  state: ResourceState<Awaited<ReturnType<typeof fetchAccounts>>>;
  onRefresh: () => void;
  isPending: (key: string) => boolean;
  onOpenAccount?: (accountId: number) => void;
  onCreate: (payload: CreateAccountPayload) => Promise<CreateAccountResponse | null>;
  onGeneratePassword: (
    account: AdminAccount,
  ) => Promise<PasswordMutationResponse | null>;
  onSetPassword: (
    account: AdminAccount,
    password: string,
    passwordConfirm: string,
  ) => Promise<boolean>;
  onUnsuspend: (account: AdminAccount) => Promise<boolean>;
  onDelete: (account: AdminAccount) => Promise<boolean | void>;
}) {
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedAccount, setSelectedAccount] = useState<AdminAccount | null>(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [revealedCredential, setRevealedCredential] = useState<{
    username?: string;
    password: string;
  } | null>(null);
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("tr-TR");
    if (!needle) return state.data?.accounts || [];
    return (state.data?.accounts || []).filter((account) =>
      [
        account.account_code,
        account.name,
        account.user_username,
        account.user_name,
        account.user_surname,
        account.user_phone,
      ]
        .filter(Boolean)
        .join(" ")
        .toLocaleLowerCase("tr-TR")
        .includes(needle),
    );
  }, [query, state.data]);

  const resetPasswordForm = () => {
    setPassword("");
    setPasswordConfirm("");
    setRevealedCredential(null);
  };

  return (
    <>
    <section>
      <SectionHeader
        title="Hesaplar"
        description="Hesapların güncel bakiye, bot ve kullanıcı durumunu tek görünümde yönetin."
        updatedAt={state.updatedAt}
        loading={state.loading}
        onRefresh={onRefresh}
        actions={
          <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
          <button
            type="button"
            onClick={() => {
              setName("");
              setPhone("");
              setRevealedCredential(null);
              setCreateOpen(true);
            }}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-[#f0b90b] px-4 py-2.5 text-xs font-black text-neutral-950 transition hover:bg-[#ffd33d]"
          >
            <UserPlus className="h-4 w-4" />
            Yeni hesap
          </button>
          <label className="relative block">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-neutral-600" />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Hesap veya kullanıcı ara"
              className="w-full rounded-xl border border-neutral-700 bg-neutral-900 py-2.5 pl-9 pr-3 text-xs text-white outline-none transition focus:border-[#f0b90b] sm:w-64"
            />
          </label>
          </div>
        }
      />
      {state.error && state.data && <RefreshWarning message={state.error} />}
      {!state.data && state.loading ? (
        <LoadingBlock label="Hesaplar yükleniyor…" />
      ) : state.error && !state.data ? (
        <ErrorBlock message={state.error} onRetry={onRefresh} />
      ) : !state.data?.accounts.length ? (
        <EmptyBlock title="Hesap bulunamadı" description="Aktif kullanıcı hesabı bulunmuyor." />
      ) : !filtered.length ? (
        <EmptyBlock
          title="Arama sonucu yok"
          description="Arama metnini değiştirip tekrar deneyin."
        />
      ) : (
        <div className="overflow-hidden rounded-2xl border border-neutral-800 bg-neutral-900/70">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-neutral-800 text-sm">
              <thead className="bg-[#181a20] text-[10px] uppercase tracking-widest text-neutral-500">
                <tr>
                  <th className="px-4 py-3 text-left">Hesap / Kullanıcı</th>
                  <th className="px-4 py-3 text-left">Durum</th>
                  <th className="px-4 py-3 text-right">Botlar</th>
                  <th className="px-4 py-3 text-right">Toplam Değer</th>
                  <th className="px-4 py-3 text-right">Günlük PnL</th>
                  <th className="px-4 py-3 text-right">Son Aktivite</th>
                  <th className="px-4 py-3 text-right">İşlem</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-800/70">
                {filtered.map((account) => {
                  return (
                    <tr key={account.account_id} className="transition hover:bg-neutral-800/30">
                      <td className="px-4 py-4">
                        <div className="font-black text-white">
                          {account.name || account.account_code || `Hesap #${account.account_id}`}
                        </div>
                        {(account.user_username || account.is_test_account) && (
                          <div className="mt-1 text-xs text-neutral-500">
                            {account.user_username ? `@${account.user_username}` : ""}
                            {account.user_username && account.is_test_account ? " · " : ""}
                            {account.is_test_account ? "Test" : ""}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-4">
                        <div className="flex flex-wrap gap-1.5">
                          <StatusBadge tone={account.user_is_online ? "green" : "neutral"}>
                            {account.user_is_online ? "Çevrimiçi" : "Çevrimdışı"}
                          </StatusBadge>
                          {account.user_is_suspended && (
                            <StatusBadge tone="red">Askıda</StatusBadge>
                          )}
                          {account.admin_isolated && (
                            <StatusBadge tone="amber">Yöneticiye kapalı</StatusBadge>
                          )}
                          {account.binance_connected ? (
                            <StatusBadge tone="green">Binance onaylandı</StatusBadge>
                          ) : account.spot_balance_status === "no_keys" ? (
                            <StatusBadge tone="neutral">Binance'e bağlanmadı</StatusBadge>
                          ) : (
                            <StatusBadge tone="amber">
                              {account.binance_connection_label ||
                                "Binance bağlantısı doğrulanamadı"}
                            </StatusBadge>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-4 text-right">
                        <strong className="text-white">{account.active_bots}</strong>
                        <span className="text-neutral-600"> / {account.total_bots}</span>
                      </td>
                      <td className="px-4 py-4 text-right font-mono font-bold text-white">
                        {account.admin_isolated ? (
                          <span className="text-neutral-500">Gizli</span>
                        ) : (
                          <>
                            {account.spot_balance_status === "no_keys" &&
                            account.bots_balance_usd <= 0
                              ? "—"
                              : formatUsd(account.total_usd)}
                            <div className="mt-1 text-[10px] font-normal text-neutral-500">
                              {account.spot_balance_status === "no_keys"
                                ? `Bot ${formatUsd(account.bots_balance_usd)} · Spot bağlı değil`
                                : `Bot ${formatUsd(account.bots_balance_usd)} · Spot ${formatUsd(account.spot_balance_usd)}`}
                            </div>
                          </>
                        )}
                      </td>
                      <td
                        className={`px-4 py-4 text-right font-mono font-bold ${
                          account.daily_pnl_usd >= 0 ? "text-[#0ecb81]" : "text-[#f6465d]"
                        }`}
                      >
                        {account.admin_isolated ? (
                          <span className="text-neutral-500">Gizli</span>
                        ) : (
                          <>
                            {account.daily_pnl_usd >= 0 ? "+" : ""}
                            {formatUsd(account.daily_pnl_usd)}
                            <div className="mt-1 text-[10px]">
                              {account.daily_pnl_pct >= 0 ? "+" : ""}
                              %{formatNumber(account.daily_pnl_pct, 2)}
                            </div>
                          </>
                        )}
                      </td>
                      <td className="px-4 py-4 text-right text-xs text-neutral-400">
                        {formatDate(
                          account.user_last_activity_at || account.user_last_login_at,
                        )}
                      </td>
                      <td className="px-4 py-4 text-right">
                        <div className="flex justify-end gap-2">
                          {onOpenAccount && (
                            <button
                              type="button"
                              onClick={() => onOpenAccount(account.account_id)}
                              disabled={account.admin_isolated}
                              title={
                                account.admin_isolated
                                  ? "Hesap sahibi yönetici erişimini kapattı"
                                  : "Hesap görünümünü aç"
                              }
                              className="inline-flex items-center gap-1.5 rounded-lg border border-[#f0b90b]/20 bg-[#f0b90b]/10 px-2.5 py-2 text-[10px] font-black text-[#f0b90b] transition hover:bg-[#f0b90b]/20 disabled:cursor-not-allowed disabled:opacity-35"
                            >
                              <ChevronRight className="h-3 w-3" />
                              Aç
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => {
                              resetPasswordForm();
                              setSelectedAccount(account);
                            }}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-700 bg-neutral-800/70 px-2.5 py-2 text-[10px] font-black text-neutral-200 transition hover:border-[#f0b90b]/40 hover:text-[#f0b90b]"
                          >
                            <Settings className="h-3.5 w-3.5" />
                            Ayarlar
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
    {createOpen && (
      <AdminDialog
        title="Yeni hesap oluştur"
        description="Kullanıcı için güvenli, tek kullanımlık ilk şifre otomatik hazırlanır."
        onClose={() => setCreateOpen(false)}
      >
        {revealedCredential ? (
          <CredentialPanel
            username={revealedCredential.username}
            password={revealedCredential.password}
          />
        ) : (
          <form
            className="space-y-4"
            onSubmit={async (event) => {
              event.preventDefault();
              const result = await onCreate({
                name: name.trim(),
                phone: phone.trim(),
                exchange: "BINANCE",
              });
              if (!result) return;
              setRevealedCredential({
                username: result.username,
                password: result.generated_password,
              });
            }}
          >
            <AdminField label="Adı Soyadı">
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
                autoComplete="off"
                placeholder="Adı Soyadı"
                className={adminInputClass}
              />
            </AdminField>
            <AdminField label="Telefon numarası">
              <input
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                required
                inputMode="tel"
                autoComplete="off"
                placeholder="05xx xxx xx xx"
                className={adminInputClass}
              />
            </AdminField>
            <button
              type="submit"
              disabled={isPending("account-create") || !name.trim() || !phone.trim()}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[#f0b90b] px-4 py-3 text-sm font-black text-neutral-950 transition hover:bg-[#ffd33d] disabled:opacity-50"
            >
              {isPending("account-create") ? (
                <LoaderCircle className="h-4 w-4 animate-spin" />
              ) : (
                <UserPlus className="h-4 w-4" />
              )}
              Hesabı oluştur
            </button>
          </form>
        )}
      </AdminDialog>
    )}
    {selectedAccount && (
      <AdminDialog
        title={selectedAccount.name || "Hesap ayarları"}
        description="Şifre, hesap durumu ve kalıcı hesap işlemlerini buradan yönetin."
        onClose={() => setSelectedAccount(null)}
      >
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-neutral-800 bg-neutral-900/70 p-4">
            <StatusBadge tone={selectedAccount.user_is_suspended ? "red" : "green"}>
              {selectedAccount.user_is_suspended ? "Hesap askıda" : "Hesap aktif"}
            </StatusBadge>
            <span className="text-xs text-neutral-500">
              {selectedAccount.user_phone || "Telefon bilgisi yok"}
            </span>
          </div>

          {selectedAccount.user_is_suspended && (
            <div className="rounded-2xl border border-[#0ecb81]/20 bg-[#0ecb81]/5 p-4">
              <h3 className="font-black text-white">Askıdaki hesabı kurtar</h3>
              <p className="mt-1 text-xs leading-5 text-neutral-400">
                Kullanıcı yeniden giriş yapabilir; başarısız giriş kilitleri temizlenir.
              </p>
              <button
                type="button"
                disabled={isPending(`account-unsuspend-${selectedAccount.account_id}`)}
                onClick={async () => {
                  if (await onUnsuspend(selectedAccount)) {
                    setSelectedAccount(null);
                  }
                }}
                className="mt-3 inline-flex items-center gap-2 rounded-xl bg-[#0ecb81] px-4 py-2.5 text-xs font-black text-neutral-950 disabled:opacity-50"
              >
                {isPending(`account-unsuspend-${selectedAccount.account_id}`) ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <UnlockKeyhole className="h-4 w-4" />
                )}
                Askıdan çıkar
              </button>
            </div>
          )}

          <div className="rounded-2xl border border-neutral-800 bg-neutral-900/70 p-4">
            <div className="flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-[#f0b90b]" />
              <h3 className="font-black text-white">Hesap şifresi</h3>
            </div>
            <p className="mt-1 text-xs leading-5 text-neutral-500">
              Yeni şifre ilk girişte kullanıcı tarafından değiştirilmek zorundadır.
            </p>
            {revealedCredential ? (
              <div className="mt-4">
                <CredentialPanel password={revealedCredential.password} />
                <button
                  type="button"
                  onClick={resetPasswordForm}
                  className="mt-3 text-xs font-bold text-neutral-400 hover:text-white"
                >
                  Başka bir şifre ayarla
                </button>
              </div>
            ) : (
              <div className="mt-4 space-y-3">
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Yeni şifre"
                  autoComplete="new-password"
                  className={adminInputClass}
                />
                <input
                  type="password"
                  value={passwordConfirm}
                  onChange={(event) => setPasswordConfirm(event.target.value)}
                  placeholder="Yeni şifre tekrar"
                  autoComplete="new-password"
                  className={adminInputClass}
                />
                <div className="grid gap-2 sm:grid-cols-2">
                  <button
                    type="button"
                    disabled={isPending(`account-password-generate-${selectedAccount.account_id}`)}
                    onClick={async () => {
                      const result = await onGeneratePassword(selectedAccount);
                      if (result?.generated_password) {
                        setRevealedCredential({ password: result.generated_password });
                      }
                    }}
                    className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#f0b90b]/30 bg-[#f0b90b]/10 px-3 py-2.5 text-xs font-black text-[#f0b90b] disabled:opacity-50"
                  >
                    {isPending(`account-password-generate-${selectedAccount.account_id}`) ? (
                      <LoaderCircle className="h-4 w-4 animate-spin" />
                    ) : (
                      <KeyRound className="h-4 w-4" />
                    )}
                    Güçlü şifre oluştur
                  </button>
                  <button
                    type="button"
                    disabled={
                      isPending(`account-password-set-${selectedAccount.account_id}`) ||
                      !password ||
                      !passwordConfirm
                    }
                    onClick={async () => {
                      if (await onSetPassword(selectedAccount, password, passwordConfirm)) {
                        resetPasswordForm();
                      }
                    }}
                    className="inline-flex items-center justify-center gap-2 rounded-xl bg-[#f0b90b] px-3 py-2.5 text-xs font-black text-neutral-950 disabled:opacity-50"
                  >
                    {isPending(`account-password-set-${selectedAccount.account_id}`) && (
                      <LoaderCircle className="h-4 w-4 animate-spin" />
                    )}
                    Şifreyi değiştir
                  </button>
                </div>
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-[#f6465d]/25 bg-[#f6465d]/5 p-4">
            <h3 className="font-black text-[#f6465d]">Kalıcı hesap silme</h3>
            <p className="mt-1 text-xs leading-5 text-neutral-400">
              Hesap ve ilişkili veriler silinir. Aktif bot varsa sunucu işlemi güvenle reddeder.
            </p>
            <button
              type="button"
              disabled={isPending(`account-delete-${selectedAccount.account_id}`)}
              onClick={async () => {
                const deleted = await onDelete(selectedAccount);
                if (deleted) setSelectedAccount(null);
              }}
              className="mt-3 inline-flex items-center gap-2 rounded-xl border border-[#f6465d]/30 bg-[#f6465d]/10 px-4 py-2.5 text-xs font-black text-[#f6465d] disabled:opacity-50"
            >
              {isPending(`account-delete-${selectedAccount.account_id}`) ? (
                <LoaderCircle className="h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4" />
              )}
              Hesabı sil
            </button>
          </div>
        </div>
      </AdminDialog>
    )}
    </>
  );
}

function RegistrationsTab({
  state,
  onRefresh,
  isPending,
  onReview,
}: {
  state: ResourceState<Awaited<ReturnType<typeof fetchPendingRegistrations>>>;
  onRefresh: () => void;
  isPending: (key: string) => boolean;
  onReview: (
    registrationId: number,
    approve: boolean,
    registrationLabel: string,
    ipAddress: string,
  ) => void;
}) {
  return (
    <section>
      <SectionHeader
        title="Kayıt talepleri"
        description="Bekleyen kullanıcı başvurularını doğrulayın. Red işlemi ilgili IP adresini engelleyebilir."
        updatedAt={state.updatedAt}
        loading={state.loading}
        onRefresh={onRefresh}
      />
      {state.error && state.data && <RefreshWarning message={state.error} />}
      {!state.data && state.loading ? (
        <LoadingBlock label="Kayıt talepleri yükleniyor…" />
      ) : state.error && !state.data ? (
        <ErrorBlock message={state.error} onRetry={onRefresh} />
      ) : !state.data?.pending.length ? (
        <EmptyBlock
          title="Bekleyen kayıt yok"
          description="Tüm başvurular incelenmiş görünüyor."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {state.data.pending.map((registration) => {
            const key = `registration-${registration.id}`;
            const label =
              `${registration.name || ""} ${registration.surname || ""}`.trim() ||
              `Başvuru #${registration.id}`;
            return (
              <article
                key={registration.id}
                className="rounded-2xl border border-neutral-800 bg-neutral-900/80 p-5"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="font-black text-white">{label}</h3>
                    <p className="mt-1 text-xs text-neutral-500">
                      Talep #{registration.id} · {formatDate(registration.created_at)}
                    </p>
                  </div>
                  <StatusBadge tone="amber">Bekliyor</StatusBadge>
                </div>
                <dl className="mt-5 grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-xl bg-[#181a20] p-3">
                    <dt className="text-[10px] uppercase tracking-wider text-neutral-600">
                      Telefon
                    </dt>
                    <dd className="mt-1 font-mono text-neutral-200">
                      {registration.phone || "—"}
                    </dd>
                  </div>
                  <div className="rounded-xl bg-[#181a20] p-3">
                    <dt className="text-[10px] uppercase tracking-wider text-neutral-600">
                      IP adresi
                    </dt>
                    <dd className="mt-1 font-mono text-neutral-200">
                      {registration.ip_address || "—"}
                    </dd>
                  </div>
                </dl>
                <div className="mt-4 flex gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      onReview(registration.id, true, label, registration.ip_address)
                    }
                    disabled={isPending(key)}
                    className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-[#0ecb81] px-3 py-2.5 text-xs font-black text-neutral-950 transition hover:bg-[#0bb371] disabled:opacity-50"
                  >
                    {isPending(key) ? (
                      <LoaderCircle className="h-4 w-4 animate-spin" />
                    ) : (
                      <Check className="h-4 w-4" />
                    )}
                    Onayla
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      onReview(registration.id, false, label, registration.ip_address)
                    }
                    disabled={isPending(key)}
                    className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-[#f6465d]/25 bg-[#f6465d]/10 px-3 py-2.5 text-xs font-black text-[#f6465d] transition hover:bg-[#f6465d]/20 disabled:opacity-50"
                  >
                    <X className="h-4 w-4" />
                    Reddet
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

function ChatsTab({
  state,
  onRefresh,
  isPending,
  runMutation,
  onDataChanged,
  setNotice,
  setActionError,
}: {
  state: ResourceState<Awaited<ReturnType<typeof fetchChats>>>;
  onRefresh: () => void;
  isPending: (key: string) => boolean;
  runMutation: <T>(key: string, action: () => Promise<T>) => Promise<T | null>;
  onDataChanged: (silent?: boolean) => Promise<void>;
  setNotice: (message: string) => void;
  setActionError: (message: string) => void;
}) {
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("");
  const [detail, setDetail] =
    useState<ResourceState<AdminChatMessagesResponse>>(INITIAL_CHAT_DETAIL);
  const detailAbortRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const selectedChat =
    state.data?.chats.find((chat) => chat.user_id === selectedUserId) || null;

  const filteredChats = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("tr-TR");
    if (!needle) return state.data?.chats || [];
    return (state.data?.chats || []).filter((chat) =>
      [
        chat.name,
        chat.surname,
        chat.phone,
        chat.account_code,
        String(chat.account_id),
      ]
        .join(" ")
        .toLocaleLowerCase("tr-TR")
        .includes(needle),
    );
  }, [query, state.data]);

  const loadDetail = useCallback(async (userId: number) => {
    detailAbortRef.current?.abort();
    const controller = new AbortController();
    detailAbortRef.current = controller;
    setDetail((current) => ({ ...current, loading: true, error: "" }));
    try {
      const data = await fetchChatMessages(userId, controller.signal);
      if (controller.signal.aborted) return;
      setDetail({ data, loading: false, error: "", updatedAt: new Date() });
    } catch (error) {
      if (controller.signal.aborted) return;
      setDetail((current) => ({
        ...current,
        loading: false,
        error: error instanceof Error ? error.message : "Mesajlar yüklenemedi.",
      }));
    } finally {
      if (detailAbortRef.current === controller) detailAbortRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (selectedUserId == null) {
      setDetail(INITIAL_CHAT_DETAIL);
      return;
    }
    void (async () => {
      await loadDetail(selectedUserId);
      await onDataChanged(true);
    })();
  }, [loadDetail, onDataChanged, selectedUserId]);

  useEffect(
    () => () => {
      detailAbortRef.current?.abort();
    },
    [],
  );

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ block: "end" });
  }, [detail.data?.messages.length]);

  const refreshConversation = async () => {
    if (selectedUserId != null) await loadDetail(selectedUserId);
    await onDataChanged();
  };

  const mutateChatState = async (
    action: "lock" | "unlock" | "end" | "reopen" | "clear",
  ) => {
    const threadId = detail.data?.thread_id;
    if (!threadId) return;
    if (
      action === "lock" &&
      !window.confirm("Bu sohbet kilitlensin ve kullanıcı mesaj gönderemesin mi?")
    ) {
      return;
    }
    if (
      action === "end" &&
      !window.confirm("Bu sohbet sonlandırılsın mı? Kullanıcı yeniden mesaj gönderemez.")
    ) {
      return;
    }
    if (
      action === "clear" &&
      !confirmIrreversible(
        "Sohbetteki tüm mesajlar ve puanlar silinecek.",
        "SON ONAY: Sohbet geçmişi kalıcı olarak temizlensin mi?",
      )
    ) {
      return;
    }
    const key = `chat-${action}-${threadId}`;
    const result = await runMutation(key, () => changeChatState(threadId, action));
    if (!result) return;
    const labels = {
      lock: "Sohbet kilitlendi.",
      unlock: "Sohbet kilidi açıldı.",
      end: "Sohbet sonlandırıldı.",
      reopen: "Sohbet yeniden açıldı.",
      clear: "Sohbet geçmişi temizlendi.",
    };
    setNotice(labels[action]);
    await refreshConversation();
  };

  const handleSend = async (event: React.FormEvent) => {
    event.preventDefault();
    const body = message.trim();
    if (!selectedChat || !body || body.length > CHAT_MAX_LENGTH || detail.data?.ended) {
      return;
    }
    const key = `chat-send-${selectedChat.user_id}`;
    const result = await runMutation(key, () => sendChatMessage(selectedChat.user_id, body));
    if (!result) return;
    setMessage("");
    setNotice("Mesaj gönderildi.");
    await refreshConversation();
  };

  if (!state.data && state.loading) return <LoadingBlock label="Sohbetler yükleniyor…" />;
  if (state.error && !state.data) return <ErrorBlock message={state.error} onRetry={onRefresh} />;
  if (!state.data?.chats.length) {
    return (
      <section>
        <SectionHeader
          title="Sohbetler"
          description="Kullanıcı destek konuşmalarını yönetin. Bu alan otomatik yenilenmez."
          onRefresh={onRefresh}
        />
        <EmptyBlock title="Sohbet kullanıcısı yok" description="Görüntülenecek hesap bulunamadı." />
      </section>
    );
  }

  return (
    <section>
      <SectionHeader
        title="Sohbetler"
        description="Sohbet listesi ve mesajlar yalnızca açılışta veya elle yenilenir; arka planda polling yapılmaz."
        updatedAt={state.updatedAt}
        loading={state.loading}
        onRefresh={() => void refreshConversation()}
      />
      {state.error && state.data && <RefreshWarning message={state.error} />}
      <div className="grid min-h-[620px] overflow-hidden rounded-2xl border border-neutral-800 bg-neutral-900/70 lg:grid-cols-[340px_1fr]">
        <aside className="border-b border-neutral-800 bg-[#181a20] lg:border-b-0 lg:border-r">
          <div className="border-b border-neutral-800 p-3">
            <label className="relative block">
              <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-neutral-600" />
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Kullanıcı ara"
                className="w-full rounded-xl border border-neutral-800 bg-neutral-950 py-2.5 pl-9 pr-3 text-xs text-white outline-none focus:border-[#f0b90b]"
              />
            </label>
          </div>
          <div className="max-h-[555px] overflow-y-auto">
            {!filteredChats.length ? (
              <p className="p-6 text-center text-xs text-neutral-500">Arama sonucu yok.</p>
            ) : (
              filteredChats.map((chat) => (
                <button
                  type="button"
                  key={chat.user_id}
                  onClick={() => {
                    setActionError("");
                    setSelectedUserId(chat.user_id);
                  }}
                  className={`flex w-full items-start gap-3 border-b border-neutral-800/70 p-4 text-left transition ${
                    selectedUserId === chat.user_id
                      ? "bg-[#f0b90b]/10"
                      : "hover:bg-neutral-800/40"
                  }`}
                >
                  <span
                    className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${
                      chat.online ? "bg-[#0ecb81]" : "bg-neutral-600"
                    }`}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-black text-white">
                      {`${chat.name} ${chat.surname}`.trim() ||
                        chat.account_code ||
                        `Kullanıcı #${chat.user_id}`}
                    </span>
                    <span className="mt-1 block truncate text-[11px] text-neutral-500">
                      {chat.account_code || `Hesap #${chat.account_id}`} ·{" "}
                      {formatDate(chat.last_message_at)}
                    </span>
                    <span className="mt-2 flex flex-wrap gap-1">
                      {chat.locked && <StatusBadge tone="amber">Kilitli</StatusBadge>}
                      {chat.ended && <StatusBadge tone="neutral">Bitti</StatusBadge>}
                    </span>
                  </span>
                  {chat.unread_count > 0 && (
                    <span className="rounded-full bg-[#f6465d] px-2 py-0.5 text-[10px] font-black text-white">
                      {chat.unread_count}
                    </span>
                  )}
                </button>
              ))
            )}
          </div>
        </aside>

        <div className="flex min-h-[620px] min-w-0 flex-col">
          {!selectedChat ? (
            <div className="grid flex-1 place-items-center p-8 text-center">
              <div>
                <MessageSquare className="mx-auto h-9 w-9 text-neutral-700" />
                <p className="mt-4 font-black text-neutral-300">Bir sohbet seçin</p>
                <p className="mt-1 text-sm text-neutral-600">
                  Mesaj geçmişi yalnızca seçim yaptığınızda yüklenir.
                </p>
              </div>
            </div>
          ) : (
            <>
              <div className="flex flex-col justify-between gap-3 border-b border-neutral-800 px-5 py-4 sm:flex-row sm:items-center">
                <div>
                  <h3 className="font-black text-white">
                    {`${selectedChat.name} ${selectedChat.surname}`.trim() ||
                      `Kullanıcı #${selectedChat.user_id}`}
                  </h3>
                  <p className="mt-1 text-xs text-neutral-500">
                    {selectedChat.phone || "Telefon yok"} ·{" "}
                    {selectedChat.account_code || `Hesap #${selectedChat.account_id}`}
                  </p>
                </div>
                {detail.data?.thread_id && (
                  <div className="flex flex-wrap gap-1.5">
                    {!detail.data.locked && !detail.data.ended && (
                      <ChatActionButton
                        label="Kilitle"
                        icon={LockKeyhole}
                        pending={isPending(`chat-lock-${detail.data.thread_id}`)}
                        onClick={() => void mutateChatState("lock")}
                      />
                    )}
                    {detail.data.locked && !detail.data.ended && (
                      <ChatActionButton
                        label="Kilidi aç"
                        icon={UnlockKeyhole}
                        pending={isPending(`chat-unlock-${detail.data.thread_id}`)}
                        onClick={() => void mutateChatState("unlock")}
                      />
                    )}
                    {!detail.data.ended ? (
                      <ChatActionButton
                        label="Sonlandır"
                        icon={Power}
                        pending={isPending(`chat-end-${detail.data.thread_id}`)}
                        onClick={() => void mutateChatState("end")}
                      />
                    ) : (
                      <ChatActionButton
                        label="Yeniden aç"
                        icon={RefreshCw}
                        pending={isPending(`chat-reopen-${detail.data.thread_id}`)}
                        onClick={() => void mutateChatState("reopen")}
                      />
                    )}
                    <ChatActionButton
                      label="Temizle"
                      icon={Trash2}
                      destructive
                      pending={isPending(`chat-clear-${detail.data.thread_id}`)}
                      onClick={() => void mutateChatState("clear")}
                    />
                  </div>
                )}
              </div>

              {detail.error && detail.data && (
                <div className="border-b border-[#f0b90b]/20 bg-[#f0b90b]/10 px-5 py-2 text-xs text-[#f0b90b]">
                  Mesajlar yenilenemedi; önceki konuşma gösteriliyor. {detail.error}
                </div>
              )}

              <div className="flex-1 space-y-3 overflow-y-auto p-5">
                {detail.loading && !detail.data ? (
                  <LoadingBlock label="Mesajlar yükleniyor…" />
                ) : detail.error && !detail.data ? (
                  <ErrorBlock
                    message={detail.error}
                    onRetry={() => void loadDetail(selectedChat.user_id)}
                  />
                ) : !detail.data?.messages.length ? (
                  <EmptyBlock
                    title="Henüz mesaj yok"
                    description="İlk yönetici mesajını aşağıdaki alandan gönderebilirsiniz."
                  />
                ) : (
                  detail.data.messages.map((chatMessage) => {
                    const fromAdmin = chatMessage.sender_type === "admin";
                    return (
                      <div
                        key={chatMessage.id}
                        className={`flex ${fromAdmin ? "justify-end" : "justify-start"}`}
                      >
                        <div
                          className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                            fromAdmin
                              ? "rounded-br-sm bg-[#f0b90b] text-neutral-950"
                              : "rounded-bl-sm bg-neutral-800 text-neutral-200"
                          }`}
                        >
                          <p className="whitespace-pre-wrap break-words text-sm">
                            {chatMessage.body}
                          </p>
                          <p
                            className={`mt-1 text-[10px] ${
                              fromAdmin ? "text-neutral-800/70" : "text-neutral-500"
                            }`}
                          >
                            {formatDate(chatMessage.created_at)}
                            {fromAdmin ? (chatMessage.read_at ? " · Okundu" : " · İletildi") : ""}
                          </p>
                        </div>
                      </div>
                    );
                  })
                )}
                <div ref={messagesEndRef} />
              </div>

              {detail.data?.ended ? (
                <div className="border-t border-neutral-800 bg-neutral-950/50 p-4 text-center text-sm text-neutral-400">
                  Sohbet sonlandırıldı
                  {detail.data.rating != null ? ` · Kullanıcı puanı ${detail.data.rating}/5` : ""}.
                </div>
              ) : (
                <form
                  onSubmit={(event) => void handleSend(event)}
                  className="border-t border-neutral-800 bg-[#181a20] p-4"
                >
                  <div className="flex gap-2">
                    <textarea
                      rows={2}
                      value={message}
                      onChange={(event) =>
                        setMessage(event.target.value.slice(0, CHAT_MAX_LENGTH))
                      }
                      placeholder="Yönetici yanıtını yazın…"
                      maxLength={CHAT_MAX_LENGTH}
                      className="min-h-12 flex-1 resize-none rounded-xl border border-neutral-800 bg-neutral-950 px-3 py-2.5 text-sm text-white outline-none transition focus:border-[#f0b90b]"
                    />
                    <button
                      type="submit"
                      disabled={
                        !message.trim() ||
                        isPending(`chat-send-${selectedChat.user_id}`) ||
                        detail.loading
                      }
                      className="grid w-12 place-items-center rounded-xl bg-[#f0b90b] text-neutral-950 transition hover:bg-[#d9a70a] disabled:opacity-50"
                      aria-label="Mesaj gönder"
                    >
                      {isPending(`chat-send-${selectedChat.user_id}`) ? (
                        <LoaderCircle className="h-4 w-4 animate-spin" />
                      ) : (
                        <Send className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                  <p className="mt-1 text-right text-[10px] text-neutral-600">
                    {message.length}/{CHAT_MAX_LENGTH}
                  </p>
                </form>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function ChatActionButton({
  label,
  icon: Icon,
  pending,
  destructive = false,
  onClick,
}: {
  label: string;
  icon: LucideIcon;
  pending: boolean;
  destructive?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={pending}
      className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-2 text-[10px] font-black transition disabled:opacity-50 ${
        destructive
          ? "border-[#f6465d]/20 bg-[#f6465d]/10 text-[#f6465d] hover:bg-[#f6465d]/20"
          : "border-neutral-700 bg-neutral-800 text-neutral-300 hover:text-white"
      }`}
    >
      {pending ? (
        <LoaderCircle className="h-3 w-3 animate-spin" />
      ) : (
        <Icon className="h-3 w-3" />
      )}
      {label}
    </button>
  );
}

function ServerTab({
  state,
  onRefresh,
  isPending,
  onRestart,
}: {
  state: ResourceState<Awaited<ReturnType<typeof fetchServerStats>>>;
  onRefresh: () => void;
  isPending: (key: string) => boolean;
  onRestart: () => void;
}) {
  const stats = state.data;
  const memoryPct =
    stats?.memory_mb != null && stats.memory_total_mb
      ? (stats.memory_mb / stats.memory_total_mb) * 100
      : null;

  return (
    <section>
      <SectionHeader
        title="Sunucu sağlığı"
        description="İstatistikler yalnızca bu sayfa görünürken 30 saniyede bir yenilenir. Kontrol eylemleri açık onay gerektirir."
        updatedAt={state.updatedAt}
        loading={state.loading}
        onRefresh={onRefresh}
      />
      {state.error && state.data && <RefreshWarning message={state.error} />}
      {!stats && state.loading ? (
        <LoadingBlock label="Sunucu istatistikleri yükleniyor…" />
      ) : state.error && !stats ? (
        <ErrorBlock message={state.error} onRetry={onRefresh} />
      ) : !stats ? (
        <EmptyBlock title="Sunucu verisi yok" description="İstatistik yanıtı boş döndü." />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <ServerMetric
              icon={CircleGauge}
              label="CPU kullanımı"
              value={stats.cpu_percent == null ? "—" : `%${formatNumber(stats.cpu_percent, 1)}`}
              progress={stats.cpu_percent}
            />
            <ServerMetric
              icon={Database}
              label="Bellek"
              value={
                stats.memory_mb == null
                  ? "—"
                  : `${formatNumber(stats.memory_mb)} / ${formatNumber(stats.memory_total_mb)} MB`
              }
              progress={memoryPct}
            />
            <ServerMetric
              icon={Activity}
              label="İstek sayısı"
              value={formatNumber(stats.request_count)}
              detail={stats.uptime_formatted}
            />
            <ServerMetric
              icon={Network}
              label="Ağ trafiği"
              value={
                stats.network_mbps_down == null
                  ? "İlk ölçüm hazırlanıyor"
                  : `${formatNumber(stats.network_mbps_down, 2)} Mbps ↓`
              }
              detail={
                stats.network_mbps_up == null
                  ? `Bağlantı ${formatNumber(stats.network_link_mbps)} Mbps`
                  : `${formatNumber(stats.network_mbps_up, 2)} Mbps ↑`
              }
            />
          </div>

          <div className="mt-5 grid gap-5 lg:grid-cols-[1fr_0.8fr]">
            <div className="rounded-2xl border border-neutral-800 bg-neutral-900/80 p-5">
              <h3 className="font-black text-white">Sunucu kimliği</h3>
              <dl className="mt-4 divide-y divide-neutral-800 text-sm">
                {[
                  ["IP adresi", stats.server_ip || "Sunucu tarafından ölçülemedi"],
                  ["Çalışma dizini", stats.server_cwd || "—"],
                  [
                    "Bağlantı kapasitesi",
                    stats.network_link_mbps == null
                      ? "Arayüz hızı ölçülemedi"
                      : `${formatNumber(stats.network_link_mbps)} Mbps`,
                  ],
                  ["Ölçüm desteği", stats.psutil_available ? "Aktif" : "Kısıtlı"],
                ].map(([label, value]) => (
                  <div key={label} className="grid gap-2 py-3 sm:grid-cols-[170px_1fr]">
                    <dt className="text-neutral-500">{label}</dt>
                    <dd className="break-all font-mono text-neutral-200">{value}</dd>
                  </div>
                ))}
              </dl>
            </div>

            <div className="rounded-2xl border border-[#f0b90b]/15 bg-[#f0b90b]/5 p-5">
              <div className="flex items-start gap-3">
                <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-[#f0b90b]" />
                <div>
                  <h3 className="font-black text-white">Kontrollü eylemler</h3>
                  <p className="mt-1 text-xs leading-5 text-neutral-500">
                    Bu düğmeler gerçek sunucu durumunu değiştirir. Yeniden başlatma şifre ve iki
                    ayrı onay ister.
                  </p>
                </div>
              </div>
              <div className="mt-5 space-y-2">
                <div
                  className={`flex w-full items-center justify-center gap-2 rounded-xl border px-4 py-3 text-xs font-black ${
                    stats.lockdown
                      ? "border-[#f6465d]/25 bg-[#f6465d]/10 text-[#f6465d]"
                      : "border-[#0ecb81]/20 bg-[#0ecb81]/10 text-[#0ecb81]"
                  }`}
                  role="status"
                >
                  {stats.lockdown ? (
                    <LockKeyhole className="h-4 w-4" />
                  ) : (
                    <UnlockKeyhole className="h-4 w-4" />
                  )}
                  {stats.lockdown ? "Bakım erişimi kapalı" : "Kullanıcı erişimi açık"}
                </div>
                <button
                  type="button"
                  onClick={onRestart}
                  disabled={isPending("server-restart")}
                  className="flex w-full items-center justify-center gap-2 rounded-xl border border-neutral-700 bg-neutral-900 px-4 py-3 text-xs font-black text-neutral-300 transition hover:text-white disabled:opacity-50"
                >
                  {isPending("server-restart") ? (
                    <LoaderCircle className="h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCw className="h-4 w-4" />
                  )}
                  Sunucuyu yeniden başlat
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function ServerMetric({
  icon: Icon,
  label,
  value,
  detail,
  progress,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  detail?: string;
  progress?: number | null;
}) {
  const safeProgress =
    progress == null || !Number.isFinite(progress) ? null : Math.min(100, Math.max(0, progress));
  return (
    <div className="rounded-2xl border border-neutral-800 bg-neutral-900/80 p-5">
      <Icon className="h-5 w-5 text-[#f0b90b]" />
      <p className="mt-4 text-xs font-bold uppercase tracking-widest text-neutral-500">{label}</p>
      <p className="mt-1 text-xl font-black text-white">{value}</p>
      {detail && <p className="mt-1 text-xs text-neutral-600">{detail}</p>}
      {safeProgress != null && (
        <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-neutral-800">
          <div
            className={`h-full rounded-full ${
              safeProgress >= 85
                ? "bg-[#f6465d]"
                : safeProgress >= 65
                  ? "bg-[#f0b90b]"
                  : "bg-[#0ecb81]"
            }`}
            style={{ width: `${safeProgress}%` }}
          />
        </div>
      )}
    </div>
  );
}

function PopupsTab({
  state,
  onRefresh,
  isPending,
  onCreate,
  onDelete,
}: {
  state: ResourceState<Awaited<ReturnType<typeof fetchPopups>>>;
  onRefresh: () => void;
  isPending: (key: string) => boolean;
  onCreate: (payload: CreatePopupPayload) => Promise<boolean>;
  onDelete: (popup: AdminPopup) => void;
}) {
  const [target, setTarget] = useState<AdminPopup["target"]>("normal_user");
  const [titleKey, setTitleKey] = useState<AdminPopup["title_key"]>("info");
  const [message, setMessage] = useState("");
  const [validUntil, setValidUntil] = useState(defaultPopupExpiry);
  const [maxShows, setMaxShows] = useState(1);
  const [formError, setFormError] = useState("");

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const cleanMessage = message.trim();
    const expiry = new Date(validUntil);
    if (!cleanMessage) {
      setFormError("Pop-up mesajını girin.");
      return;
    }
    if (Number.isNaN(expiry.getTime()) || expiry <= new Date()) {
      setFormError("Geçerlilik süresi gelecekte bir tarih olmalıdır.");
      return;
    }
    setFormError("");
    const saved = await onCreate({
      target,
      title_key: titleKey,
      message: cleanMessage,
      valid_until: expiry.toISOString(),
      max_shows_per_user: Math.max(1, Math.floor(maxShows)),
    });
    if (saved) {
      setMessage("");
      setValidUntil(defaultPopupExpiry());
      setMaxShows(1);
    }
  };

  return (
    <section>
      <SectionHeader
        title="Pop-up yayınları"
        description="Kullanıcı hedefli duyuruları gerçek yayın endpointiyle oluşturun ve geçmiş yayınları yönetin."
        updatedAt={state.updatedAt}
        loading={state.loading}
        onRefresh={onRefresh}
      />
      {state.error && state.data && <RefreshWarning message={state.error} />}
      <div className="grid gap-5 xl:grid-cols-[420px_1fr]">
        <form
          onSubmit={(event) => void handleSubmit(event)}
          className="h-fit rounded-2xl border border-neutral-800 bg-neutral-900/80 p-5"
        >
          <h3 className="font-black text-white">Yeni yayın</h3>
          <p className="mt-1 text-xs text-neutral-500">
            Yayın hemen aktif olur ve seçilen tarihte sona erer.
          </p>
          <div className="mt-5 space-y-4">
            <label className="block">
              <span className="text-xs font-bold text-neutral-400">Hedef kitle</span>
              <select
                value={target}
                onChange={(event) => setTarget(event.target.value as AdminPopup["target"])}
                className="mt-1.5 w-full rounded-xl border border-neutral-800 bg-[#181a20] px-3 py-2.5 text-sm text-white outline-none focus:border-[#f0b90b]"
              >
                <option value="normal_user">Normal kullanıcılar</option>
                <option value="first_login">İlk giriş yapanlar</option>
              </select>
            </label>
            <label className="block">
              <span className="text-xs font-bold text-neutral-400">Yayın türü</span>
              <select
                value={titleKey}
                onChange={(event) =>
                  setTitleKey(event.target.value as AdminPopup["title_key"])
                }
                className="mt-1.5 w-full rounded-xl border border-neutral-800 bg-[#181a20] px-3 py-2.5 text-sm text-white outline-none focus:border-[#f0b90b]"
              >
                <option value="info">Bilgi</option>
                <option value="warning">Uyarı</option>
                <option value="success">Başarı</option>
                <option value="maintenance">Bakım</option>
                <option value="announcement">Duyuru</option>
              </select>
            </label>
            <label className="block">
              <span className="text-xs font-bold text-neutral-400">Mesaj</span>
              <textarea
                rows={5}
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                className="mt-1.5 w-full resize-y rounded-xl border border-neutral-800 bg-[#181a20] px-3 py-2.5 text-sm text-white outline-none focus:border-[#f0b90b]"
                placeholder="Kullanıcılara gösterilecek mesaj…"
              />
            </label>
            <div className="grid grid-cols-[1fr_110px] gap-3">
              <label className="block">
                <span className="text-xs font-bold text-neutral-400">Geçerlilik</span>
                <input
                  type="datetime-local"
                  value={validUntil}
                  onChange={(event) => setValidUntil(event.target.value)}
                  className="mt-1.5 w-full rounded-xl border border-neutral-800 bg-[#181a20] px-3 py-2.5 text-xs text-white outline-none focus:border-[#f0b90b]"
                />
              </label>
              <label className="block">
                <span className="text-xs font-bold text-neutral-400">Gösterim</span>
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={maxShows}
                  onChange={(event) =>
                    setMaxShows(Math.min(100, Math.max(1, Number(event.target.value) || 1)))
                  }
                  className="mt-1.5 w-full rounded-xl border border-neutral-800 bg-[#181a20] px-3 py-2.5 text-sm text-white outline-none focus:border-[#f0b90b]"
                />
              </label>
            </div>
          </div>
          {formError && (
            <p className="mt-3 text-xs font-semibold text-[#f6465d]" role="alert">
              {formError}
            </p>
          )}
          <button
            type="submit"
            disabled={isPending("popup-create")}
            className="mt-5 flex w-full items-center justify-center gap-2 rounded-xl bg-[#f0b90b] px-4 py-3 text-xs font-black text-neutral-950 transition hover:bg-[#d9a70a] disabled:opacity-50"
          >
            {isPending("popup-create") ? (
              <LoaderCircle className="h-4 w-4 animate-spin" />
            ) : (
              <BellRing className="h-4 w-4" />
            )}
            Yayınla
          </button>
        </form>

        <div>
          {!state.data && state.loading ? (
            <LoadingBlock label="Pop-up yayınları yükleniyor…" />
          ) : state.error && !state.data ? (
            <ErrorBlock message={state.error} onRetry={onRefresh} />
          ) : !state.data?.popups.length ? (
            <EmptyBlock title="Henüz yayın yok" description="İlk pop-up yayınını oluşturabilirsiniz." />
          ) : (
            <div className="space-y-3">
              {state.data.popups.map((popup) => {
                const deleteKey = `popup-delete-${popup.id}`;
                return (
                  <article
                    key={popup.id}
                    className="rounded-2xl border border-neutral-800 bg-neutral-900/80 p-5"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <StatusBadge tone={popup.is_active ? "green" : "neutral"}>
                            {popup.is_active ? "Aktif" : "Süresi doldu"}
                          </StatusBadge>
                          <StatusBadge tone="amber">{popup.title_key}</StatusBadge>
                          <span className="text-[10px] font-bold uppercase tracking-wider text-neutral-600">
                            {popup.target === "first_login"
                              ? "İlk giriş"
                              : "Normal kullanıcı"}
                          </span>
                        </div>
                        <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-neutral-200">
                          {popup.message}
                        </p>
                        <p className="mt-3 text-xs text-neutral-600">
                          #{popup.id} · Bitiş {formatDate(popup.valid_until)} · Kullanıcı başına{" "}
                          {popup.max_shows_per_user} gösterim
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => onDelete(popup)}
                        disabled={isPending(deleteKey)}
                        className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-[#f6465d]/20 bg-[#f6465d]/10 text-[#f6465d] transition hover:bg-[#f6465d]/20 disabled:opacity-50"
                        aria-label={`#${popup.id} pop-up kaldır`}
                      >
                        {isPending(deleteKey) ? (
                          <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Trash2 className="h-3.5 w-3.5" />
                        )}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function ErrorsTab({
  state,
  count,
  onRefresh,
  onClear,
  clearing,
}: {
  state: ResourceState<Awaited<ReturnType<typeof fetchErrorLogs>>>;
  count: number | null;
  onRefresh: () => void;
  onClear: () => void;
  clearing: boolean;
}) {
  return (
    <section>
      <SectionHeader
        title="Hata logları"
        description="Aynı kaynak, mesaj ve yol birleşimi gruplanır. Liste otomatik yenilenmez."
        updatedAt={state.updatedAt}
        loading={state.loading}
        onRefresh={onRefresh}
        actions={
          <button
            type="button"
            onClick={onClear}
            disabled={clearing || !count}
            className="inline-flex items-center gap-2 rounded-xl border border-red-300/20 bg-red-300/[0.06] px-3.5 py-2.5 text-xs font-black text-red-200 transition hover:bg-red-300/10 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {clearing ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
            Hataları sıfırla
          </button>
        }
      />
      {state.error && state.data && <RefreshWarning message={state.error} />}
      <div className="mb-4 flex items-center gap-2 text-xs text-neutral-500">
        <FileWarning className="h-4 w-4 text-[#f6465d]" />
        Toplam ham kayıt: <strong className="text-neutral-200">{count ?? "—"}</strong>
      </div>
      {!state.data && state.loading ? (
        <LoadingBlock label="Hata kayıtları yükleniyor…" />
      ) : state.error && !state.data ? (
        <ErrorBlock message={state.error} onRetry={onRefresh} />
      ) : !state.data?.errors.length ? (
        <EmptyBlock title="Hata kaydı yok" description="Sistem hata logu listesi temiz görünüyor." />
      ) : (
        <div className="space-y-3">
          {state.data.errors.map((error) => (
            <details
              key={error.id}
              className="group rounded-2xl border border-neutral-800 bg-neutral-900/80 open:border-[#f6465d]/20"
            >
              <summary className="flex cursor-pointer list-none items-start gap-3 p-5">
                <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-[#f6465d]/10">
                  <AlertTriangle className="h-4 w-4 text-[#f6465d]" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <strong className="break-all text-sm text-white">
                      {error.source || "Bilinmeyen kaynak"}
                    </strong>
                    {error.occurrence_count > 1 && (
                      <StatusBadge tone="red">{error.occurrence_count} tekrar</StatusBadge>
                    )}
                    {error.is_admin && <StatusBadge tone="amber">Admin</StatusBadge>}
                  </div>
                  <p className="mt-2 line-clamp-2 break-words text-sm text-neutral-300">
                    {error.message || "Hata mesajı yok"}
                  </p>
                  <p className="mt-2 text-[10px] text-neutral-600">
                    #{error.id} · {formatDate(error.created_at)}
                    {error.path ? ` · ${error.path}` : ""}
                  </p>
                </div>
                <ChevronRight className="mt-2 h-4 w-4 shrink-0 text-neutral-600 transition group-open:rotate-90" />
              </summary>
              <div className="border-t border-neutral-800 px-5 py-4">
                <dl className="grid gap-3 text-xs sm:grid-cols-2">
                  {[
                    ["Detay", error.detail || "—"],
                    ["Request ID", error.request_id || "—"],
                    ["Kullanıcı", error.user_label || "—"],
                    ["Hesap", error.account_label || "—"],
                    ["İstemci IP", error.client_ip || "—"],
                    ["User Agent", error.user_agent || "—"],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-xl bg-[#181a20] p-3">
                      <dt className="text-[10px] font-bold uppercase tracking-wider text-neutral-600">
                        {label}
                      </dt>
                      <dd className="mt-1 break-all font-mono leading-5 text-neutral-300">
                        {value}
                      </dd>
                    </div>
                  ))}
                </dl>
                {error.context != null && (
                  <div className="mt-3 rounded-xl bg-neutral-950 p-3">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-600">
                      Context
                    </p>
                    <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words text-[11px] leading-5 text-neutral-400">
                      {typeof error.context === "string"
                        ? error.context
                        : JSON.stringify(error.context, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            </details>
          ))}
        </div>
      )}
    </section>
  );
}
