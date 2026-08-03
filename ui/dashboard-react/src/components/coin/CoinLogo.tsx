import { useEffect, useMemo, useState } from "react";

const KNOWN_COIN_LOGOS = new Set([
  "1000CAT", "1000CHEEMS", "1INCH", "1MBABYDOGE", "2Z", "AAVE", "ACA",
  "ACM", "ACT", "ADA", "AGLD", "ALCX", "ALGO", "ALLO", "ANIME", "ANKR",
  "API3", "APT", "ARB", "ARK", "ARPA", "ASTER", "ASTR", "ATOM", "AUDIO",
  "AVAX", "AXL", "AXS", "BABY", "BAND", "BANK", "BAT", "BB", "BCH", "BNB",
  "BONK", "BTC", "BUSD", "CAKE", "CELO", "CFX", "CHZ", "CKB", "COMP",
  "CRV", "DAI", "DASH", "DCR", "DENT", "DGB", "DOGE", "DOT", "DYDX",
  "EGLD", "ENJ", "ENS", "ETC", "ETH", "FDUSD", "FET", "FIL", "FIO",
  "FLOKI", "FLUX", "FOGO", "FRAX", "GALA", "GLMR", "GRT", "HBAR",
  "HMSTR", "HOLO", "ICP", "ICX", "IMX", "INJ", "IOTA", "JASMY", "JTO",
  "JUP", "KAVA", "KNC", "KSM", "LDO", "LINK", "LRC", "LTC", "LUNA",
  "LUNC", "MAGIC", "MANA", "MANTA", "MINA", "MOVR", "NEAR", "NEO", "NFP",
  "ONE", "ONT", "PAXG", "PENDLE", "PEPE", "POL", "POND", "PUNDIX",
  "PYUSD", "QTUM", "QUICK", "RE", "RENDER", "ROSE", "RPL", "RUNE", "RVN",
  "SAND", "SATS", "SEI", "SHIB", "SKL", "SKY", "SNX", "SOL", "SPELL",
  "STEEM", "STORJ", "SUI", "SUSHI", "SYN", "THETA", "TLM", "TON",
  "TRUMP", "TRX", "TUSD", "UNI", "USDC", "USDP", "USDT", "VET", "WBTC",
  "WIF", "WLD", "XLM", "XRP", "XTZ", "YFI", "ZEC", "ZEN", "ZIL", "ZRX",
]);

const SYMBOL_ALIASES: Record<string, string> = {
  XBT: "BTC",
  LUNA2: "LUNA",
  "1000SHIB": "SHIB",
  "1000PEPE": "PEPE",
  "1000FLOKI": "FLOKI",
  "1000LUNC": "LUNC",
  "1000BONK": "BONK",
  "1000SATS": "SATS",
};

const QUOTES = [
  "FDUSD", "USDT", "USDC", "BUSD", "TUSD", "USDP", "BIDR", "IDRT",
  "USDS", "PYUSD", "BVND", "BRL", "TRY", "EUR", "GBP", "AUD", "UAH",
  "RUB", "PLN", "RON", "ARS", "COP", "MXN", "AED", "ZAR", "NGN",
  "DAI", "PAX", "VAI", "BTC", "ETH", "BNB", "JPY", "CZK",
];

export function normalizeCoinSymbol(value: unknown): string {
  let symbol = String(value ?? "").trim().toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (!symbol) return "";
  if (!KNOWN_COIN_LOGOS.has(symbol)) {
    const quote = QUOTES.find(
      (candidate) => symbol.length > candidate.length && symbol.endsWith(candidate),
    );
    if (quote) symbol = symbol.slice(0, -quote.length);
  }
  if (symbol === "USD") symbol = "USDT";
  return SYMBOL_ALIASES[symbol] || symbol;
}

export function splitTradingSymbol(value: unknown): {
  base: string;
  quote: string;
  label: string;
} {
  const raw = String(value ?? "").trim().toUpperCase().replace(/[^A-Z0-9]/g, "");
  const quote =
    QUOTES.find(
      (candidate) => raw.length > candidate.length && raw.endsWith(candidate),
    ) || "USDT";
  const base = raw.endsWith(quote) ? raw.slice(0, -quote.length) : raw;
  return {
    base: base || raw || "—",
    quote,
    label: base ? `${base}/${quote}` : raw || "—",
  };
}

export default function CoinLogo({
  symbol,
  size = 40,
  eager = false,
  className = "",
}: {
  symbol: unknown;
  size?: number;
  eager?: boolean;
  className?: string;
}) {
  const normalized = useMemo(() => normalizeCoinSymbol(symbol), [symbol]);
  const [failed, setFailed] = useState(false);

  useEffect(() => setFailed(false), [normalized]);

  const canLoad = Boolean(normalized && KNOWN_COIN_LOGOS.has(normalized) && !failed);
  const initials = normalized.slice(0, 2) || "?";
  const imageClass =
    normalized === "USDT"
      ? "p-0 scale-[1.06] rounded-full"
      : normalized === "SOL"
        ? "p-0 scale-[1.34]"
        : "p-[7%]";
  const shellClass = normalized === "SOL" ? "bg-black" : "";

  return (
    <span
      aria-hidden="true"
      className={`relative inline-grid shrink-0 place-items-center overflow-hidden rounded-full border border-white/10 bg-gradient-to-br from-white/10 to-white/[0.025] shadow-[0_8px_24px_rgba(0,0,0,.22)] ${shellClass} ${className}`}
      style={{ width: size, height: size }}
    >
      <span className="text-[10px] font-black tracking-tight text-neutral-400">
        {initials}
      </span>
      {canLoad && (
        <img
          src={`/ui/assets/coins/${encodeURIComponent(normalized)}.png`}
          alt=""
          loading={eager ? "eager" : "lazy"}
          decoding="async"
          onError={() => setFailed(true)}
          className={`absolute inset-0 h-full w-full object-contain ${imageClass}`}
        />
      )}
    </span>
  );
}
