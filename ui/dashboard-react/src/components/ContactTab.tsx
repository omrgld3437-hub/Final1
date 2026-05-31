import React, { useState, useEffect, useRef } from "react";
import { MessageSquare, Send, ThumbsUp, RotateCcw, AlertTriangle } from "lucide-react";
import { ChatHistory } from "../types";
import { apiFetch } from "../lib/api";

export default function ContactTab() {
  const [chat, setChat] = useState<ChatHistory>({
    locked: false,
    ended: false,
    rating: null,
    messages: []
  });
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const fetchChatHistory = () => {
    apiFetch<ChatHistory>("/api/auth/chat")
      .then((data) => {
        if (data) setChat(data);
      })
      .catch(console.error);
  };

  useEffect(() => {
    fetchChatHistory();
    // Poll chat every 3 seconds for mock/AI responses
    const interval = setInterval(fetchChatHistory, 3000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    // Scroll to latest message
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat.messages]);

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || input.length > 500) return;

    // Optimistically add user bubble, and make admin "type" or simulate
    const prompt = input;
    setInput("");
    setIsTyping(true);

    apiFetch<ChatHistory>("/api/auth/chat/send", {
      method: "POST",
      body: JSON.stringify({ message: prompt }),
    })
      .then((data) => {
        if (data) setChat(data);
        setIsTyping(false);
      })
      .catch(err => {
        console.error(err);
        setIsTyping(false);
      });
  };

  const handleEndChat = (rating: number) => {
    apiFetch<ChatHistory>("/api/auth/chat/end", {
      method: "POST",
      body: JSON.stringify({ rating }),
    })
      .then((data) => {
        if (data) setChat(data);
      })
      .catch(console.error);
  };

  const handleReopenChat = () => {
    apiFetch<ChatHistory>("/api/auth/chat-reopen", { method: "POST" })
      .then((data) => {
        if (data) setChat(data);
      })
      .catch(console.error);
  };

  return (
    <div className="max-w-2xl mx-auto bg-neutral-900 border border-neutral-800 rounded-2xl shadow-2xl flex flex-col h-[520px] overflow-hidden">
      {/* Header */}
      <div className="bg-[#1e2026] border-b border-neutral-800 px-6 py-4 flex justify-between items-center text-white">
        <div className="flex items-center space-x-3">
          <div className="w-2.5 h-2.5 bg-[#0ecb81] rounded-full animate-pulse" />
          <div>
            <h3 className="font-bold text-base">Yönetim Destek &amp; AI Yardım</h3>
            <p className="text-[10px] text-neutral-400">Bizimle anlık, güvenli ve şifreli destek süreci</p>
          </div>
        </div>
        <MessageSquare className="w-5 h-5 text-[#f0b90b]" />
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-6 space-y-4 max-h-[3400px]">
        {chat.messages.map(msg => {
          const isAdmin = msg.sender_type === "admin";
          return (
            <div 
              key={msg.id} 
              className={`flex flex-col ${isAdmin ? "items-start" : "items-end"} space-y-1`}
            >
              <div 
                className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm word-wrap break-word ${
                  isAdmin 
                    ? "bg-neutral-800 text-neutral-200 rounded-tl-sm" 
                    : "bg-[#f0b90b] text-neutral-950 font-medium rounded-tr-sm"
                }`}
              >
                {msg.body}
              </div>
              <span className="text-[10px] text-neutral-500 px-1 font-mono">
                {new Date(msg.created_at).toLocaleTimeString(undefined, {hour: '2-digit', minute:'2-digit'})}
              </span>
            </div>
          );
        })}

        {isTyping && (
          <div className="flex items-center space-x-1 pl-3 py-1">
            <span className="w-2 h-2 bg-neutral-500 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
            <span className="w-2 h-2 bg-neutral-500 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
            <span className="w-2 h-2 bg-neutral-500 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Chat Ended / Blocked Banners */}
      {chat.ended ? (
        <div className="bg-neutral-950/80 p-6 text-center space-y-3.5 border-t border-neutral-800">
          <div className="text-sm font-bold text-neutral-200">Sohbet görüşmesi sonlandırıldı.</div>
          
          {chat.rating ? (
            <div className="text-xs text-neutral-400 font-medium flex items-center justify-center gap-1">
              Verdiğiniz Puan: <strong className="text-[#f0b90b]">{"★".repeat(chat.rating)}</strong> ({chat.rating}/5)
            </div>
          ) : (
            <div className="space-y-2">
              <span className="text-xs text-neutral-400 block">Sohbeti puanlayarak kapatın:</span>
              <div className="flex justify-center gap-1.5">
                {[1, 2, 3, 4, 5].map(star => (
                  <button
                    key={star}
                    onClick={() => handleEndChat(star)}
                    className="text-2xl text-neutral-600 hover:text-[#f0b90b] hover:scale-110 active:scale-95 transition"
                  >
                    ★
                  </button>
                ))}
              </div>
            </div>
          )}

          <button
            onClick={handleReopenChat}
            className="px-4 py-2 bg-neutral-800 hover:bg-neutral-700 text-white text-xs font-bold rounded-xl transition flex items-center justify-center gap-1.5 mx-auto"
          >
            <RotateCcw className="w-3.5 h-3.5" /> Yeni Sohbet Başlat
          </button>
        </div>
      ) : (
        /* Footer Input Form */
        <div>
          {/* Character warning */}
          {input.length > 400 && (
            <div className="px-6 py-1 bg-[#f6465d]/10 border-t border-[#f6465d]/20 text-[10px] text-[#f6465d] flex items-center gap-1 font-semibold">
              <AlertTriangle className="w-3 h-3 shrink-0" />
              <span>Maksimum 500 karakter sınırına yaklaşıyorsunuz ({input.length}/500)</span>
            </div>
          )}

          <form 
            onSubmit={handleSendMessage}
            className="bg-[#1e2026] border-t border-neutral-800 px-6 py-4 flex gap-3 items-center"
          >
            <input
              type="text"
              value={input}
              onChange={e => setInput(e.target.value.slice(0, 500))}
              placeholder="Destek talebinizi yazın..."
              className="flex-1 bg-[#121418] border border-neutral-800 hover:border-neutral-700 focus:border-[#f0b90b] text-sm text-white rounded-xl px-4 py-2.5 focus:outline-none focus:ring-1 focus:ring-[#f0b90b] transition"
            />
            
            <button
              type="submit"
              disabled={!input.trim()}
              className="w-10 h-10 rounded-full bg-[#f0b90b] hover:bg-[#c9930a] text-neutral-900 flex items-center justify-center hover:scale-105 active:scale-95 transition disabled:opacity-50 disabled:pointer-events-none"
            >
              <Send className="w-4 h-4 mr-0.5" />
            </button>

            {chat.messages.length > 1 && (
              <button
                type="button"
                onClick={() => handleEndChat(5)}
                className="px-3 py-2 text-xs bg-neutral-800 hover:bg-neutral-700 text-neutral-300 font-bold rounded-lg transition"
              >
                Sonlandır
              </button>
            )}
          </form>
        </div>
      )}
    </div>
  );
}
