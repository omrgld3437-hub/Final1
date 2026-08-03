import React, { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, MessageSquare, RotateCcw, Send } from "lucide-react";
import { ChatHistory, ChatMessage } from "../types";
import { useDashboard } from "../context/DashboardContext";
import { apiFetch } from "../lib/api";

const CHAT_MAX_LENGTH = 2000;
const FAST_POLL_MS = 2500;
const MAX_IDLE_POLL_MS = 15000;
const MAX_ERROR_POLL_MS = 30000;

interface ChatSnapshot extends ChatHistory {
  thread_id?: number | null;
  count?: number;
  reopened_at?: string | null;
  admin_typing?: boolean;
}

interface ChatMutationResponse {
  success?: boolean;
  message?: string;
  message_id?: number;
  created_at?: string | null;
  rating?: number | null;
}

interface PollOutcome {
  changed: boolean;
  typing: boolean;
  failed: boolean;
}

const EMPTY_CHAT: ChatSnapshot = {
  locked: false,
  ended: false,
  rating: null,
  messages: [],
  admin_typing: false,
};

function normalizeChatSnapshot(data: ChatSnapshot | null | undefined): ChatSnapshot {
  if (!data || typeof data !== "object") return EMPTY_CHAT;
  return {
    thread_id: data.thread_id ?? null,
    count: Number.isFinite(Number(data.count)) ? Number(data.count) : data.messages?.length ?? 0,
    reopened_at: data.reopened_at ?? null,
    locked: Boolean(data.locked),
    ended: Boolean(data.ended),
    rating: data.rating == null ? null : Number(data.rating),
    admin_typing: Boolean(data.admin_typing),
    messages: Array.isArray(data.messages) ? data.messages : [],
  };
}

function chatSignature(chat: ChatSnapshot): string {
  return JSON.stringify({
    locked: chat.locked,
    ended: chat.ended,
    rating: chat.rating,
    typing: chat.admin_typing,
    messages: chat.messages.map((message) => [
      message.id,
      message.sender_type,
      message.body,
      message.created_at,
      message.read_at || null,
    ]),
  });
}

function messageTime(createdAt: string): string {
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("tr-TR", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Istanbul",
  });
}

export default function ContactTab() {
  const { accountId } = useDashboard();
  const [chat, setChat] = useState<ChatSnapshot>(EMPTY_CHAT);
  const [input, setInput] = useState("");
  const [ratingPrompt, setRatingPrompt] = useState(false);
  const [pendingAction, setPendingAction] = useState<"send" | "end" | "reopen" | null>(null);
  const [error, setError] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const requestInFlightRef = useRef<Promise<PollOutcome> | null>(null);
  const mutationInFlightRef = useRef(false);
  const lastSignatureRef = useRef("");
  const readPendingRef = useRef(new Set<number>());

  const refreshChat = useCallback(
    async (open = false, force = false): Promise<PollOutcome> => {
      if (!accountId) return { changed: false, typing: false, failed: true };

      if (requestInFlightRef.current) {
        const activeOutcome = await requestInFlightRef.current;
        if (!force) return activeOutcome;
      }

      const request = (async (): Promise<PollOutcome> => {
        try {
          const query = new URLSearchParams({ account_id: String(accountId) });
          if (open) query.set("open", "1");
          if (force) query.set("_t", String(Date.now()));
          const data = await apiFetch<ChatSnapshot>(`/api/auth/chat?${query.toString()}`);
          const nextChat = normalizeChatSnapshot(data);
          const nextSignature = chatSignature(nextChat);
          const changed = nextSignature !== lastSignatureRef.current;
          lastSignatureRef.current = nextSignature;
          setChat(nextChat);
          setError("");

          const unreadAdminIds = nextChat.messages
            .filter(
              (message) =>
                message.sender_type === "admin" &&
                !message.read_at &&
                !readPendingRef.current.has(message.id)
            )
            .map((message) => message.id);

          if (unreadAdminIds.length > 0) {
            unreadAdminIds.forEach((id) => readPendingRef.current.add(id));
            void apiFetch<ChatMutationResponse>("/api/auth/chat/read", {
              method: "POST",
              body: JSON.stringify({
                account_id: accountId,
                message_ids: unreadAdminIds,
              }),
            }).catch(() => {
              unreadAdminIds.forEach((id) => readPendingRef.current.delete(id));
            });
          }

          return {
            changed,
            typing: Boolean(nextChat.admin_typing),
            failed: false,
          };
        } catch (requestError) {
          console.error(requestError);
          setError("Mesajlar şu anda yenilenemiyor. Bağlantı yeniden denenecek.");
          return { changed: false, typing: false, failed: true };
        }
      })();

      requestInFlightRef.current = request;
      try {
        return await request;
      } finally {
        if (requestInFlightRef.current === request) requestInFlightRef.current = null;
      }
    },
    [accountId]
  );

  useEffect(() => {
    let stopped = false;
    let timer: number | null = null;
    let nextDelay = FAST_POLL_MS;

    lastSignatureRef.current = "";
    readPendingRef.current.clear();
    setChat(EMPTY_CHAT);
    setError("");
    setRatingPrompt(false);

    const clearTimer = () => {
      if (timer != null) {
        window.clearTimeout(timer);
        timer = null;
      }
    };

    const schedule = (delay: number) => {
      clearTimer();
      if (!stopped) timer = window.setTimeout(() => void poll(false), delay);
    };

    const poll = async (open: boolean) => {
      if (stopped) return;
      if (document.visibilityState !== "visible") {
        schedule(MAX_IDLE_POLL_MS);
        return;
      }

      const outcome = await refreshChat(open);
      if (stopped) return;
      if (outcome.failed) {
        nextDelay = Math.min(Math.max(nextDelay * 2, 5000), MAX_ERROR_POLL_MS);
      } else if (outcome.changed || outcome.typing) {
        nextDelay = FAST_POLL_MS;
      } else {
        nextDelay = Math.min(Math.round(nextDelay * 1.5), MAX_IDLE_POLL_MS);
      }
      schedule(nextDelay);
    };

    const wake = () => {
      if (document.visibilityState !== "visible") return;
      nextDelay = FAST_POLL_MS;
      clearTimer();
      void poll(false);
    };

    void poll(true);
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("focus", wake);
    window.addEventListener("online", wake);

    return () => {
      stopped = true;
      clearTimer();
      document.removeEventListener("visibilitychange", wake);
      window.removeEventListener("focus", wake);
      window.removeEventListener("online", wake);
    };
  }, [accountId, refreshChat]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat.messages.length, chat.admin_typing]);

  const handleSendMessage = async (event: React.FormEvent) => {
    event.preventDefault();
    const message = input.trim();
    if (
      mutationInFlightRef.current ||
      !message ||
      message.length > CHAT_MAX_LENGTH ||
      chat.locked ||
      chat.ended
    ) {
      return;
    }

    mutationInFlightRef.current = true;
    setPendingAction("send");
    setError("");
    try {
      const result = await apiFetch<ChatMutationResponse>("/api/auth/chat/send", {
        method: "POST",
        body: JSON.stringify({ account_id: accountId, message }),
      });
      setInput("");

      if (result?.message_id) {
        const confirmedMessage: ChatMessage = {
          id: result.message_id,
          sender_type: "user",
          body: message,
          created_at: result.created_at || new Date().toISOString(),
        };
        setChat((current) => {
          if (current.messages.some((item) => item.id === confirmedMessage.id)) return current;
          return { ...current, messages: [...current.messages, confirmedMessage] };
        });
      }
      await refreshChat(false, true);
    } catch (sendError) {
      console.error(sendError);
      setError(sendError instanceof Error ? sendError.message : "Mesaj gönderilemedi.");
    } finally {
      mutationInFlightRef.current = false;
      setPendingAction(null);
    }
  };

  const handleEndChat = async (rating: number) => {
    if (mutationInFlightRef.current || rating < 1 || rating > 5) return;
    mutationInFlightRef.current = true;
    setPendingAction("end");
    setError("");
    try {
      const result = await apiFetch<ChatMutationResponse>("/api/auth/chat/end", {
        method: "POST",
        body: JSON.stringify({ account_id: accountId, rating }),
      });
      setChat((current) => ({
        ...current,
        ended: true,
        rating: result?.rating ?? rating,
        admin_typing: false,
      }));
      setRatingPrompt(false);
      await refreshChat(false, true);
    } catch (endError) {
      console.error(endError);
      setError(endError instanceof Error ? endError.message : "Sohbet sonlandırılamadı.");
    } finally {
      mutationInFlightRef.current = false;
      setPendingAction(null);
    }
  };

  const handleReopenChat = async () => {
    if (mutationInFlightRef.current) return;
    mutationInFlightRef.current = true;
    setPendingAction("reopen");
    setError("");
    try {
      await apiFetch<ChatMutationResponse>("/api/auth/chat-reopen", {
        method: "POST",
        body: JSON.stringify({ account_id: accountId }),
      });
      await refreshChat(true, true);
    } catch (reopenError) {
      console.error(reopenError);
      setError(reopenError instanceof Error ? reopenError.message : "Sohbet yeniden açılamadı.");
    } finally {
      mutationInFlightRef.current = false;
      setPendingAction(null);
    }
  };

  return (
    <div className="max-w-2xl mx-auto bg-neutral-900 border border-neutral-800 rounded-2xl shadow-2xl flex flex-col h-[520px] overflow-hidden">
      <div className="bg-[#1e2026] border-b border-neutral-800 px-6 py-4 flex justify-between items-center text-white">
        <div className="flex items-center space-x-3">
          <div
            className={`w-2.5 h-2.5 rounded-full ${
              error ? "bg-[#f6465d]" : chat.locked || chat.ended ? "bg-neutral-500" : "bg-[#0ecb81]"
            }`}
          />
          <div>
            <h3 className="font-bold text-base">Yönetim Destek &amp; AI Yardım</h3>
            <p className="text-[10px] text-neutral-400">
              {chat.locked
                ? "Sohbet yönetim tarafından kilitlendi"
                : chat.ended
                  ? "Sohbet tamamlandı"
                  : "Güvenli destek görüşmesi"}
            </p>
          </div>
        </div>
        <MessageSquare className="w-5 h-5 text-[#f0b90b]" />
      </div>

      {error && (
        <div
          className="px-6 py-2 bg-[#f6465d]/10 border-b border-[#f6465d]/20 text-xs text-[#f6465d]"
          role="alert"
        >
          {error}
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-6 space-y-4" aria-live="polite">
        {chat.messages.length === 0 && !chat.admin_typing && (
          <p className="text-sm text-neutral-500 text-center py-10">Henüz mesaj yok.</p>
        )}
        {chat.messages.map((message) => {
          const isAdmin = message.sender_type === "admin";
          return (
            <div
              key={message.id}
              className={`flex flex-col ${isAdmin ? "items-start" : "items-end"} space-y-1`}
            >
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm break-words whitespace-pre-wrap ${
                  isAdmin
                    ? "bg-neutral-800 text-neutral-200 rounded-tl-sm"
                    : "bg-[#f0b90b] text-neutral-950 font-medium rounded-tr-sm"
                }`}
              >
                {message.body}
              </div>
              <span className="text-[10px] text-neutral-500 px-1 font-mono">
                {messageTime(message.created_at)}
                {!isAdmin && <span title={message.read_at ? "Okundu" : "İletildi"}> {message.read_at ? "✓✓" : "✓"}</span>}
              </span>
            </div>
          );
        })}

        {chat.admin_typing && !chat.locked && !chat.ended && (
          <div className="flex items-center space-x-1 pl-3 py-1" aria-label="Yönetim yazıyor">
            <span className="w-2 h-2 bg-neutral-500 rounded-full animate-bounce" />
            <span
              className="w-2 h-2 bg-neutral-500 rounded-full animate-bounce"
              style={{ animationDelay: "150ms" }}
            />
            <span
              className="w-2 h-2 bg-neutral-500 rounded-full animate-bounce"
              style={{ animationDelay: "300ms" }}
            />
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {chat.ended ? (
        <div className="bg-neutral-950/80 p-6 text-center space-y-3.5 border-t border-neutral-800">
          <div className="text-sm font-bold text-neutral-200">Sohbet görüşmesi sonlandırıldı.</div>
          {chat.rating != null && (
            <div className="text-xs text-neutral-400 font-medium">
              Verdiğiniz puan:{" "}
              <strong className="text-[#f0b90b]">{"★".repeat(chat.rating)}</strong> ({chat.rating}/5)
            </div>
          )}
          <button
            type="button"
            onClick={() => void handleReopenChat()}
            disabled={pendingAction !== null}
            className="px-4 py-2 bg-neutral-800 hover:bg-neutral-700 text-white text-xs font-bold rounded-xl transition flex items-center justify-center gap-1.5 mx-auto disabled:opacity-50"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            {pendingAction === "reopen" ? "Açılıyor…" : "Yeni Sohbet Başlat"}
          </button>
        </div>
      ) : chat.locked ? (
        <div className="bg-[#f6465d]/10 border-t border-[#f6465d]/20 px-6 py-4 text-xs text-[#f6465d]">
          Sohbet kilitlendi. Yeni mesaj gönderemezsiniz.
        </div>
      ) : ratingPrompt ? (
        <div className="bg-[#1e2026] border-t border-neutral-800 px-6 py-4 text-center space-y-3">
          <span className="text-xs text-neutral-400 block">Sohbeti puanlayarak sonlandırın:</span>
          <div className="flex justify-center gap-1.5">
            {[1, 2, 3, 4, 5].map((star) => (
              <button
                type="button"
                key={star}
                onClick={() => void handleEndChat(star)}
                disabled={pendingAction !== null}
                className="text-2xl text-neutral-600 hover:text-[#f0b90b] hover:scale-110 active:scale-95 transition disabled:opacity-50"
                aria-label={`${star} yıldız ver ve sohbeti sonlandır`}
              >
                ★
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => setRatingPrompt(false)}
            disabled={pendingAction !== null}
            className="text-xs text-neutral-400 hover:text-white disabled:opacity-50"
          >
            Vazgeç
          </button>
        </div>
      ) : (
        <div>
          {input.length > 1800 && (
            <div className="px-6 py-1 bg-[#f6465d]/10 border-t border-[#f6465d]/20 text-[10px] text-[#f6465d] flex items-center gap-1 font-semibold">
              <AlertTriangle className="w-3 h-3 shrink-0" />
              <span>
                Maksimum {CHAT_MAX_LENGTH} karakter sınırına yaklaşıyorsunuz ({input.length}/
                {CHAT_MAX_LENGTH})
              </span>
            </div>
          )}

          <form
            onSubmit={(event) => void handleSendMessage(event)}
            className="bg-[#1e2026] border-t border-neutral-800 px-6 py-4 flex gap-3 items-center"
          >
            <input
              type="text"
              value={input}
              onChange={(event) => setInput(event.target.value.slice(0, CHAT_MAX_LENGTH))}
              placeholder="Destek talebinizi yazın..."
              maxLength={CHAT_MAX_LENGTH}
              className="flex-1 bg-[#121418] border border-neutral-800 hover:border-neutral-700 focus:border-[#f0b90b] text-sm text-white rounded-xl px-4 py-2.5 focus:outline-none focus:ring-1 focus:ring-[#f0b90b] transition"
            />
            <button
              type="submit"
              disabled={!input.trim() || pendingAction !== null}
              className="w-10 h-10 rounded-full bg-[#f0b90b] hover:bg-[#c9930a] text-neutral-900 flex items-center justify-center hover:scale-105 active:scale-95 transition disabled:opacity-50 disabled:pointer-events-none"
              aria-label="Mesajı gönder"
            >
              <Send className="w-4 h-4 mr-0.5" />
            </button>

            {chat.messages.length > 0 && (
              <button
                type="button"
                onClick={() => setRatingPrompt(true)}
                disabled={pendingAction !== null}
                className="px-3 py-2 text-xs bg-neutral-800 hover:bg-neutral-700 text-neutral-300 font-bold rounded-lg transition disabled:opacity-50"
              >
                {pendingAction === "end" ? "Sonlandırılıyor…" : "Sonlandır"}
              </button>
            )}
          </form>
        </div>
      )}
    </div>
  );
}
