import { useCallback, useEffect, useState } from "react";

export type AppTab =
  | "binance"
  | "trade"
  | "bots"
  | "finance"
  | "contact"
  | "settings";

const VALID_TABS = new Set<AppTab>([
  "binance",
  "trade",
  "bots",
  "finance",
  "contact",
  "settings",
]);

function readTab(): AppTab {
  const tab = new URLSearchParams(window.location.search).get("tab") as AppTab | null;
  return tab && VALID_TABS.has(tab) ? tab : "binance";
}

export function useTabNavigation(): [AppTab, (tab: AppTab) => void] {
  const [tab, setTabState] = useState<AppTab>(readTab);

  useEffect(() => {
    const onPopState = () => setTabState(readTab());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const setTab = useCallback((next: AppTab) => {
    setTabState(next);
    const url = new URL(window.location.href);
    if (next === "binance") url.searchParams.delete("tab");
    else url.searchParams.set("tab", next);
    window.history.pushState({}, "", `${url.pathname}${url.search}${url.hash}`);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  return [tab, setTab];
}

