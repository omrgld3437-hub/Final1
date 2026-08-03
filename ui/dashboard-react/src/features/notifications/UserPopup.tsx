import { useCallback, useEffect, useRef, useState } from "react";
import { BellRing, CheckCircle2, Info, Megaphone, ShieldAlert, X } from "lucide-react";
import { useDashboard } from "../../context/DashboardContext";
import { apiRequest } from "../../core/api/http";

interface PopupMessage {
  id: number;
  title_key: "info" | "warning" | "success" | "maintenance" | "announcement";
  message: string;
  valid_until?: string;
}

const TITLES: Record<PopupMessage["title_key"], string> = {
  info: "Bilgilendirme",
  warning: "Önemli uyarı",
  success: "İşlem tamamlandı",
  maintenance: "Bakım bilgisi",
  announcement: "Duyuru",
};

export default function UserPopup() {
  const { isAdmin, isFirstLogin } = useDashboard();
  const [popup, setPopup] = useState<PopupMessage | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (isAdmin) return;
    let stopped = false;
    let loading = false;
    const load = async () => {
      if (loading || document.hidden) return;
      loading = true;
      try {
        let response = await apiRequest<{ popup?: PopupMessage | null }>(
          `/api/auth/popup/active?first_login=${isFirstLogin ? "true" : "false"}`,
          { dedupe: false, redirectOnAuthError: false },
        );
        if (isFirstLogin && !response.popup) {
          response = await apiRequest<{ popup?: PopupMessage | null }>(
            "/api/auth/popup/active?first_login=false",
            { dedupe: false, redirectOnAuthError: false },
          );
        }
        if (stopped || !response.popup) return;
        const seenKey = `ayserose_popup_seen_${response.popup.id}`;
        if (sessionStorage.getItem(seenKey) !== "1") setPopup(response.popup);
      } catch {
        // Bildirim akışı ana çalışma yüzeyini engellemez.
      } finally {
        loading = false;
      }
    };
    void load();
    const timer = window.setInterval(load, 60_000);
    const onVisible = () => void load();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [isAdmin, isFirstLogin]);

  const dismiss = useCallback(async () => {
    if (!popup) return;
    sessionStorage.setItem(`ayserose_popup_seen_${popup.id}`, "1");
    setPopup(null);
    try {
      await apiRequest("/api/auth/popup/dismiss", {
        method: "POST",
        body: JSON.stringify({ popup_id: popup.id }),
        redirectOnAuthError: false,
        dedupe: false,
      });
    } catch {
      // Yerel oturumda tekrar açılmasını engelledik; sunucu bir sonraki ziyarette dener.
    }
  }, [popup]);

  useEffect(() => {
    if (!popup) return;
    const previousOverflow = document.body.style.overflow;
    const previousFocus = document.activeElement as HTMLElement | null;
    const focusFrame = window.requestAnimationFrame(() => closeButtonRef.current?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") void dismiss();
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, [dismiss, popup]);

  if (!popup) return null;
  const Icon =
    popup.title_key === "success"
      ? CheckCircle2
      : popup.title_key === "warning" || popup.title_key === "maintenance"
        ? ShieldAlert
        : popup.title_key === "announcement"
          ? Megaphone
          : Info;

  return (
    <div className="fixed inset-0 z-[80] grid place-items-center bg-black/80 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="user-popup-title">
      <section className="w-full max-w-lg overflow-hidden rounded-[1.75rem] border border-fuchsia-300/20 bg-[#191a20] shadow-[0_35px_120px_rgba(0,0,0,.7)]">
        <header className="flex items-start justify-between gap-4 border-b border-white/8 p-5">
          <div className="flex items-center gap-3">
            <span className="grid h-11 w-11 place-items-center rounded-2xl border border-fuchsia-300/15 bg-fuchsia-300/[0.07] text-fuchsia-100">
              <Icon className="h-5 w-5" />
            </span>
            <div>
              <p className="flex items-center gap-1.5 text-[9px] font-black uppercase tracking-[0.18em] text-fuchsia-200">
                <BellRing className="h-3 w-3" /> ayserose bildirimi
              </p>
              <h2 id="user-popup-title" className="mt-1 text-lg font-black text-white">
                {TITLES[popup.title_key] || TITLES.info}
              </h2>
            </div>
          </div>
          <button ref={closeButtonRef} type="button" onClick={() => void dismiss()} aria-label="Bildirimi kapat" className="grid h-10 w-10 place-items-center rounded-xl border border-white/8 text-neutral-400 transition hover:bg-white/5 hover:text-white focus:outline-none focus:ring-2 focus:ring-fuchsia-300/70">
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="p-5">
          <p className="whitespace-pre-wrap text-sm leading-7 text-neutral-300">{popup.message}</p>
          <button type="button" onClick={() => void dismiss()} className="mt-6 w-full rounded-xl bg-gradient-to-r from-fuchsia-300 to-violet-300 px-5 py-3 text-xs font-black text-neutral-950">
            Anladım
          </button>
        </div>
      </section>
    </div>
  );
}
