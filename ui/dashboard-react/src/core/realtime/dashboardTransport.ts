import { accountUrl, apiRequest } from "../api/http";

export type DashboardTransportStatus =
  | "connecting"
  | "live"
  | "fallback"
  | "offline"
  | "stopped";

export interface DashboardEnvelope {
  ok?: boolean;
  data?: Record<string, unknown>;
  meta?: {
    request_id?: string;
    server_ms?: number;
    transport?: string;
    trimmed_fields?: string[];
  };
}

export interface DashboardTransportHandlers {
  onData: (payload: DashboardEnvelope) => void;
  onStatus: (status: DashboardTransportStatus) => void;
  onError?: (error: unknown) => void;
}

// Kartlar hızlı bot özetinden gelir; ağır KPI hesapları ana ekranı bekletmez.
const FIELDS = "prices,wallet,bots";
const FALLBACK_VISIBLE_MS = 8_000;
const FALLBACK_HIDDEN_MS = 30_000;

export class DashboardTransport {
  private readonly accountId: number;
  private readonly handlers: DashboardTransportHandlers;
  private source: EventSource | null = null;
  private timer: number | null = null;
  private stopped = false;
  private fallbackInFlight = false;
  private receivedStreamData = false;
  private reconnectAttempt = 0;
  private nextReconnectAt = 0;

  constructor(accountId: number, handlers: DashboardTransportHandlers) {
    this.accountId = accountId;
    this.handlers = handlers;
  }

  start(): void {
    this.stop(false);
    this.stopped = false;
    this.handlers.onStatus("connecting");
    void this.bootstrap().finally(() => {
      if (!this.stopped) this.openStream();
    });
    document.addEventListener("visibilitychange", this.onVisibilityChange);
    window.addEventListener("online", this.onOnline);
    window.addEventListener("offline", this.onOffline);
  }

  stop(emit = true): void {
    this.stopped = true;
    this.closeStream();
    this.clearTimer();
    document.removeEventListener("visibilitychange", this.onVisibilityChange);
    window.removeEventListener("online", this.onOnline);
    window.removeEventListener("offline", this.onOffline);
    if (emit) this.handlers.onStatus("stopped");
  }

  refresh(): Promise<void> {
    return this.snapshot(true);
  }

  private readonly onVisibilityChange = (): void => {
    if (this.stopped) return;
    if (document.hidden) {
      this.closeStream();
      this.startFallback();
    } else {
      void this.snapshot();
      this.reconnectAttempt = 0;
      this.nextReconnectAt = 0;
      this.clearTimer();
      this.openStream();
    }
  };

  private readonly onOnline = (): void => {
    if (this.stopped) return;
    this.handlers.onStatus("connecting");
    void this.snapshot();
    this.openStream();
  };

  private readonly onOffline = (): void => {
    this.closeStream();
    this.clearTimer();
    this.handlers.onStatus("offline");
  };

  private streamUrl(): string {
    return accountUrl("/api/dashboard/stream", this.accountId, { fields: FIELDS });
  }

  private snapshotUrl(): string {
    return accountUrl("/api/dashboard/snapshot", this.accountId, { fields: FIELDS });
  }

  private bootstrapUrl(): string {
    return accountUrl("/api/dashboard/bootstrap", this.accountId);
  }

  private async bootstrap(): Promise<void> {
    if (this.stopped || !navigator.onLine) return;
    try {
      const payload = await apiRequest<DashboardEnvelope>(this.bootstrapUrl(), {
        timeoutMs: 8_000,
        dedupe: true,
      });
      if (!this.stopped) this.handlers.onData(payload);
    } catch (error) {
      this.handlers.onError?.(error);
      await this.snapshot();
    }
  }

  private async snapshot(force = false): Promise<void> {
    if (this.stopped) {
      if (force) throw new Error("Canlı veri bağlantısı kapalı.");
      return;
    }
    if (!navigator.onLine) {
      if (force) throw new Error("İnternet bağlantısı yok.");
      return;
    }
    if (!force && this.fallbackInFlight) return;
    if (!force) this.fallbackInFlight = true;
    try {
      const url = force
        ? `${this.snapshotUrl()}&refresh_at=${Date.now()}`
        : this.snapshotUrl();
      const payload = await apiRequest<DashboardEnvelope>(url, {
        timeoutMs: 12_000,
        dedupe: !force,
      });
      if (!this.stopped) this.handlers.onData(payload);
    } catch (error) {
      this.handlers.onError?.(error);
      if (!this.source && !this.stopped) this.handlers.onStatus("offline");
      if (force) throw error;
    } finally {
      if (!force) this.fallbackInFlight = false;
    }
  }

  private openStream(): void {
    if (
      this.stopped ||
      this.source ||
      !navigator.onLine ||
      document.hidden ||
      Date.now() < this.nextReconnectAt ||
      typeof EventSource === "undefined"
    ) {
      if (!this.source && !this.stopped) this.startFallback();
      return;
    }
    this.receivedStreamData = false;
    try {
      const source = new EventSource(this.streamUrl(), { withCredentials: true });
      source.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as DashboardEnvelope;
          this.receivedStreamData = true;
          this.reconnectAttempt = 0;
          this.nextReconnectAt = 0;
          this.clearTimer();
          this.handlers.onStatus("live");
          this.handlers.onData(payload);
        } catch (error) {
          this.handlers.onError?.(error);
        }
      };
      source.onerror = () => {
        this.closeStream();
        this.planReconnect();
        if (!this.stopped) this.startFallback();
      };
      this.source = source;
      window.setTimeout(() => {
        if (!this.stopped && this.source === source && !this.receivedStreamData) {
          this.closeStream();
          this.planReconnect();
          this.startFallback();
        }
      }, 10_000);
    } catch (error) {
      this.handlers.onError?.(error);
      this.startFallback();
    }
  }

  private closeStream(): void {
    this.source?.close();
    this.source = null;
  }

  private startFallback(): void {
    if (this.stopped) return;
    this.handlers.onStatus("fallback");
    void this.snapshot();
    this.scheduleFallback();
  }

  private planReconnect(): void {
    this.reconnectAttempt += 1;
    const base = Math.min(30_000, 1_000 * 2 ** Math.min(this.reconnectAttempt, 5));
    const jitter = Math.round(base * (0.75 + Math.random() * 0.5));
    this.nextReconnectAt = Date.now() + jitter;
  }

  private scheduleFallback(): void {
    this.clearTimer();
    if (this.stopped) return;
    const pollDelay = document.hidden ? FALLBACK_HIDDEN_MS : FALLBACK_VISIBLE_MS;
    const reconnectDelay = Math.max(0, this.nextReconnectAt - Date.now());
    const delay =
      !document.hidden && reconnectDelay > 0
        ? Math.min(pollDelay, reconnectDelay)
        : pollDelay;
    this.timer = window.setTimeout(async () => {
      await this.snapshot();
      if (!this.stopped && !this.source) {
        if (!document.hidden && Date.now() >= this.nextReconnectAt) this.openStream();
        if (!this.source) this.scheduleFallback();
      }
    }, delay);
  }

  private clearTimer(): void {
    if (this.timer != null) {
      window.clearTimeout(this.timer);
      this.timer = null;
    }
  }
}
