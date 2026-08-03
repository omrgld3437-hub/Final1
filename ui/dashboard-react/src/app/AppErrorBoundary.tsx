import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class AppErrorBoundary extends Component<Props, State> {
  declare readonly props: Props;
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("[frontend-v2] render boundary", error, info.componentStack);
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children;
    return (
      <main className="min-h-screen bg-[#101115] text-neutral-100 grid place-items-center p-6">
        <section className="w-full max-w-lg rounded-3xl border border-red-500/20 bg-[#191b21] p-8 shadow-2xl">
          <p className="text-xs font-bold uppercase tracking-[0.24em] text-red-300">
            Güvenli görünüm
          </p>
          <h1 className="mt-3 text-2xl font-black text-white">
            Bu bölüm görüntülenirken bir sorun oluştu.
          </h1>
          <p className="mt-3 text-sm leading-6 text-neutral-400">
            Açık işlemleriniz etkilenmedi. Son başarılı veriler korunuyor; sayfayı
            yenileyerek yeniden bağlanabilirsiniz.
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-6 rounded-xl bg-[#f0b90b] px-5 py-3 text-sm font-black text-neutral-950"
          >
            Güvenli şekilde yenile
          </button>
        </section>
      </main>
    );
  }
}
