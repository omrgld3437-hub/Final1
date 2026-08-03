import { useState, type FormEvent } from "react";
import { KeyRound, LoaderCircle, LogOut, ShieldCheck } from "lucide-react";
import { apiRequest } from "../../core/api/http";
import { passwordIssue } from "./passwordPolicy";

export default function PasswordChangeGate({
  accountId,
  displayName,
  onCompleted,
  onLogout,
}: {
  accountId: number;
  displayName: string;
  onCompleted: () => void;
  onLogout: () => void;
}) {
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const [name = "", ...surnameParts] = displayName.trim().split(/\s+/);
    const issue = passwordIssue(password, name, surnameParts.join(" "));
    if (issue) {
      setError(issue);
      return;
    }
    if (password !== confirmation) {
      setError("Şifreler eşleşmiyor.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const response = await apiRequest<{ success?: boolean; message?: string }>(
        "/api/auth/change-password",
        {
          method: "POST",
          body: JSON.stringify({
            account_id: accountId,
            new_password: password,
            new_password_confirm: confirmation,
          }),
          timeoutMs: 15_000,
        },
      );
      if (!response?.success) throw new Error("Şifre yenileme onaylanamadı.");
      onCompleted();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Şifre yenilenemedi.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="auth-page grid min-h-screen place-items-center overflow-hidden bg-[#0d0e12] p-5 text-neutral-100">
      <div className="auth-orb auth-orb-one" />
      <div className="auth-orb auth-orb-two" />
      <section className="relative w-full max-w-lg rounded-[2rem] border border-white/10 bg-[#17181e]/95 p-7 shadow-[0_30px_100px_rgba(0,0,0,.6)] backdrop-blur-xl sm:p-9">
        <div className="grid h-12 w-12 place-items-center rounded-2xl bg-amber-300/10 text-[#f0b90b]">
          <KeyRound className="h-6 w-6" />
        </div>
        <p className="mt-6 text-xs font-black uppercase tracking-[0.2em] text-[#f0b90b]">
          Zorunlu güvenlik adımı
        </p>
        <h1 className="mt-2 text-3xl font-black tracking-tight text-white">
          Tek kullanımlık şifrenizi yenileyin
        </h1>
        <p className="mt-3 text-sm leading-6 text-neutral-400">
          Finansal ekranlar ve işlem komutları, kalıcı şifrenizi belirleyene kadar
          kapalıdır.
        </p>

        <form onSubmit={submit} className="mt-7 space-y-4">
          <label className="block">
            <span className="mb-2 block text-xs font-bold text-neutral-400">Yeni şifre</span>
            <input
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="w-full rounded-xl border border-neutral-700 bg-[#101116] px-4 py-3 text-sm text-white outline-none transition focus:border-[#f0b90b]"
              required
            />
          </label>
          <label className="block">
            <span className="mb-2 block text-xs font-bold text-neutral-400">
              Yeni şifre tekrarı
            </span>
            <input
              type="password"
              autoComplete="new-password"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              className="w-full rounded-xl border border-neutral-700 bg-[#101116] px-4 py-3 text-sm text-white outline-none transition focus:border-[#f0b90b]"
              required
            />
          </label>
          <div className="rounded-xl border border-white/8 bg-white/[0.025] p-3 text-xs leading-5 text-neutral-500">
            En az 10 karakter; büyük ve küçük harf, rakam ve noktalama işareti kullanın.
          </div>
          {error && (
            <p role="alert" className="rounded-xl border border-red-400/20 bg-red-400/5 px-4 py-3 text-xs text-red-200">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={submitting}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#f0b90b] px-5 py-3.5 text-sm font-black text-neutral-950 transition hover:bg-[#d9a70a] disabled:opacity-60"
          >
            {submitting ? (
              <LoaderCircle className="h-4 w-4 animate-spin" />
            ) : (
              <ShieldCheck className="h-4 w-4" />
            )}
            {submitting ? "Güvenli şekilde yenileniyor…" : "Şifreyi yenile ve devam et"}
          </button>
        </form>

        <button
          type="button"
          onClick={onLogout}
          className="mt-4 flex w-full items-center justify-center gap-2 py-2 text-xs font-bold text-neutral-500 hover:text-neutral-300"
        >
          <LogOut className="h-3.5 w-3.5" />
          Güvenli çıkış
        </button>
      </section>
    </main>
  );
}
