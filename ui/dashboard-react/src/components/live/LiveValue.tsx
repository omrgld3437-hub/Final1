import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

type Movement = "up" | "down" | null;

function numeric(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export default function LiveValue({
  value,
  children,
  className = "",
  toneBySign = false,
  neutralAtZero = true,
  title,
}: {
  value: unknown;
  children: ReactNode;
  className?: string;
  toneBySign?: boolean;
  neutralAtZero?: boolean;
  title?: string;
}) {
  const current = numeric(value);
  const previousRef = useRef<number | null>(null);
  const timerRef = useRef<number | null>(null);
  const [movement, setMovement] = useState<Movement>(null);

  useEffect(() => {
    if (current === null) {
      previousRef.current = null;
      setMovement(null);
      return;
    }
    const previous = previousRef.current;
    previousRef.current = current;
    if (previous === null || previous === current) return;
    setMovement(current > previous ? "up" : "down");
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      setMovement(null);
      timerRef.current = null;
    }, 760);
    return () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [current]);

  const signedTone =
    toneBySign && current !== null
      ? current > 0
        ? "text-emerald-300"
        : current < 0
          ? "text-red-300"
          : neutralAtZero
            ? "text-neutral-300"
            : "text-emerald-300"
      : "";

  return (
    <span
      className={`live-value ${movement ? `live-value--${movement}` : ""} ${signedTone} ${className}`}
      data-movement={movement || undefined}
      title={title}
    >
      {children}
    </span>
  );
}
