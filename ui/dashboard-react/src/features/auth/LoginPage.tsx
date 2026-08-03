import { useState, type FormEvent } from "react";
import { ArrowRight, Eye, EyeOff, ShieldCheck } from "lucide-react";
import BrandMark from "../../components/brand/BrandMark";
import { ApiError, apiRequest } from "../../core/api/http";

interface LoginResponse {
  success: boolean;
  user: {
    must_change_password?: boolean;
    is_first_login?: boolean;
  };
}

function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "Giriş tamamlanamadı.";
}

export default function LoginPage({
  onAuthenticated,
}: {
  onAuthenticated: (result: {
    mustChangePassword: boolean;
    isFirstLogin: boolean;
  }) => void;
}) {
  const [identity, setIdentity] = useState(
    () => localStorage.getItem("last_login_phone") || "",
  );
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!identity.trim() || !password) {
      setError("Kullanıcı bilgilerinizi eksiksiz girin.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const response = await apiRequest<LoginResponse>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ phone: identity.trim(), password }),
        redirectOnAuthError: false,
        timeoutMs: 15_000,
        dedupe: false,
      });
      localStorage.setItem("last_login_phone", identity.trim());
      localStorage.removeItem("token");
      sessionStorage.removeItem("token");
      const mustChangePassword = response.user?.must_change_password === true;
      const isFirstLogin = response.user?.is_first_login === true;
      if (mustChangePassword) sessionStorage.setItem("v2_must_change_password", "1");
      else sessionStorage.removeItem("v2_must_change_password");
      if (isFirstLogin) sessionStorage.setItem("v2_first_login", "1");
      else sessionStorage.removeItem("v2_first_login");
      onAuthenticated({ mustChangePassword, isFirstLogin });
    } catch (cause) {
      setError(messageOf(cause));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="auth-page grid min-h-screen place-items-center overflow-hidden bg-[#0d0e12] px-4 py-[max(1.5rem,env(safe-area-inset-top))] text-neutral-100">
      <div className="auth-orb auth-orb-one" />
      <div className="auth-orb auth-orb-two" />
      <section className="w-full max-w-md rounded-[2rem] border border-white/10 bg-[#17181e]/86 p-6 shadow-[0_30px_100px_rgba(0,0,0,.58)] backdrop-blur-xl sm:p-8">
        <div className="flex justify-center">
          <BrandMark />
        </div>
        <div className="mt-8 text-center">
          <p className="inline-flex items-center gap-2 rounded-full border border-fuchsia-300/15 bg-fuchsia-300/5 px-3 py-1.5 text-[10px] font-black uppercase tracking-[0.18em] text-fuchsia-200">
            <ShieldCheck className="h-3.5 w-3.5" /> Güvenli hesap girişi
          </p>
          <h1 className="mt-4 text-2xl font-black tracking-[-0.03em] text-white">
            Hesabınıza giriş yapın
          </h1>
        </div>

        <form className="mt-7 space-y-4" onSubmit={submit}>
          <label className="block">
            <span className="mb-2 block text-xs font-bold text-neutral-400">
              Telefon veya kullanıcı adı
            </span>
            <input
              value={identity}
              onChange={(event) => setIdentity(event.target.value)}
              autoComplete="username"
              autoFocus
              className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3.5 text-sm text-white outline-none transition focus:border-fuchsia-300/50 focus:ring-4 focus:ring-fuchsia-300/5"
            />
          </label>
          <label className="block">
            <span className="mb-2 block text-xs font-bold text-neutral-400">Şifre</span>
            <span className="relative block">
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3.5 pr-12 text-sm text-white outline-none transition focus:border-fuchsia-300/50 focus:ring-4 focus:ring-fuchsia-300/5"
              />
              <button
                type="button"
                onClick={() => setShowPassword((current) => !current)}
                className="absolute inset-y-0 right-0 grid w-12 place-items-center text-neutral-500 hover:text-white"
                aria-label={showPassword ? "Şifreyi gizle" : "Şifreyi göster"}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </span>
          </label>

          {error && (
            <p role="alert" className="rounded-xl border border-red-400/20 bg-red-400/5 px-4 py-3 text-xs leading-5 text-red-200">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-[#d494ec] to-[#f0b90b] px-5 py-3.5 text-sm font-black text-[#111217] shadow-lg shadow-fuchsia-900/10 transition hover:brightness-110 disabled:cursor-wait disabled:opacity-60"
          >
            {submitting ? "Giriş doğrulanıyor…" : "Giriş yap"}
            {!submitting && <ArrowRight className="h-4 w-4" />}
          </button>
        </form>
      </section>
    </main>
  );
}
