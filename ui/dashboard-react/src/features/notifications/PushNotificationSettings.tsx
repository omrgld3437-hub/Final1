import React, { useEffect, useState } from "react";
import { BellRing, CheckCircle2, LoaderCircle, ShieldCheck } from "lucide-react";
import { apiFetch } from "../../lib/api";

type PushState = "checking" | "enabled" | "disabled" | "blocked" | "unsupported" | "error";

interface PushNotificationSettingsProps {
  accountId: number;
}

function supportsWebPush(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

function applicationServerKey(value: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const raw = window.atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let index = 0; index < raw.length; index += 1) bytes[index] = raw.charCodeAt(index);
  return bytes;
}

function subscriptionPayload(accountId: number, subscription: PushSubscription) {
  const json = subscription.toJSON();
  return {
    account_id: accountId,
    endpoint: subscription.endpoint,
    keys: {
      p256dh: String(json.keys?.p256dh || ""),
      auth: String(json.keys?.auth || ""),
    },
  };
}

export default function PushNotificationSettings({ accountId }: PushNotificationSettingsProps) {
  const [state, setState] = useState<PushState>("checking");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;
    if (!supportsWebPush()) {
      setState("unsupported");
      return () => { active = false; };
    }

    navigator.serviceWorker.ready
      .then((registration) => registration.pushManager.getSubscription())
      .then(async (subscription) => {
        if (!active) return;
        if (!subscription) {
          setState(Notification.permission === "denied" ? "blocked" : "disabled");
          return;
        }
        await apiFetch("/api/push/subscriptions", {
          method: "POST",
          body: JSON.stringify(subscriptionPayload(accountId, subscription)),
        });
        if (active) setState("enabled");
      })
      .catch(() => {
        if (active) setState("error");
      });

    return () => { active = false; };
  }, [accountId]);

  const enable = async () => {
    setBusy(true);
    setMessage("");
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setState(permission === "denied" ? "blocked" : "disabled");
        setMessage("Bildirim izni verilmedi.");
        return;
      }
      const [{ public_key: publicKey }, registration] = await Promise.all([
        apiFetch<{ public_key: string }>("/api/push/vapid-public-key"),
        navigator.serviceWorker.ready,
      ]);
      let subscription = await registration.pushManager.getSubscription();
      if (!subscription) {
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: applicationServerKey(publicKey),
        });
      }
      await apiFetch("/api/push/subscriptions", {
        method: "POST",
        body: JSON.stringify(subscriptionPayload(accountId, subscription)),
      });
      setState("enabled");
      setMessage("Bot işlem bildirimleri bu cihazda açıldı.");
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "Bildirimler açılamadı.");
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    setBusy(true);
    setMessage("");
    try {
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.getSubscription();
      if (subscription) {
        await apiFetch("/api/push/subscriptions", {
          method: "DELETE",
          body: JSON.stringify({ account_id: accountId, endpoint: subscription.endpoint }),
        });
        await subscription.unsubscribe();
      }
      setState("disabled");
      setMessage("Bot işlem bildirimleri bu cihazda kapatıldı.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Bildirim ayarı değiştirilemedi.");
    } finally {
      setBusy(false);
    }
  };

  const enabled = state === "enabled";
  const unavailable = state === "unsupported" || state === "blocked";
  const statusText = enabled
    ? "Bu cihazda aktif"
    : state === "blocked"
      ? "Tarayıcı izni kapalı"
      : state === "unsupported"
        ? "Bu tarayıcı desteklemiyor"
        : "Bu cihazda kapalı";

  return (
    <section className="relative overflow-hidden rounded-2xl border border-fuchsia-300/15 bg-gradient-to-br from-fuchsia-400/[0.08] via-violet-400/[0.04] to-white/[0.015] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] sm:p-5">
      <div className="pointer-events-none absolute -right-12 -top-16 h-40 w-40 rounded-full bg-fuchsia-400/10 blur-3xl" />
      <div className="relative flex items-center gap-3">
        <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border ${enabled ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-200" : "border-fuchsia-300/15 bg-fuchsia-300/[0.08] text-fuchsia-200"}`}>
          {enabled ? <CheckCircle2 className="h-5 w-5" /> : <BellRing className="h-5 w-5" />}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-base font-black leading-5 text-white">Bot işlem bildirimleri</p>
          <span className={`mt-1.5 inline-flex rounded-full border px-2.5 py-1 text-[9px] font-black ${enabled ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-200" : "border-white/10 bg-white/[0.035] text-neutral-400"}`}>
            {state === "checking" ? "Kontrol ediliyor" : statusText}
          </span>
        </div>
      </div>

      <p className="relative mt-4 text-[11px] leading-5 text-neutral-300">
        Grid alış, grid satış ve kâr işlemleri gerçekleştiğinde sembol ve tur bilgisiyle bildirim alın.
      </p>

      <div className="relative mt-3 flex items-center gap-1.5 text-[10px] font-bold text-violet-200/80">
        <ShieldCheck className="h-3.5 w-3.5 shrink-0" />
        <span>iPhone kilit ekranı bildirimleri desteklenir.</span>
      </div>

      <button
        type="button"
        disabled={busy || state === "checking" || unavailable}
        onClick={enabled ? disable : enable}
        className="relative mt-4 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-fuchsia-300/20 bg-fuchsia-300/10 px-4 text-xs font-black text-fuchsia-100 transition hover:bg-fuchsia-300/15 disabled:cursor-not-allowed disabled:opacity-45"
      >
        {busy && <LoaderCircle className="h-4 w-4 animate-spin" />}
        {enabled ? "Bildirimleri kapat" : "Bildirimleri aç"}
      </button>

      {message && <p role="status" className="relative mt-3 rounded-xl border border-white/8 bg-black/15 px-3 py-2 text-center text-[10px] text-neutral-300">{message}</p>}
    </section>
  );
}
