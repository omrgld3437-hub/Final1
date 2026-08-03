import {
  AlertTriangle,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Bot as BotIcon,
  CircleDollarSign,
  Layers3,
  LoaderCircle,
  Plus,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  WalletCards,
  X,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import { createPortal } from "react-dom";
import { useDashboard } from "../context/DashboardContext";
import BotCreateStudio, {
  type GridDraft,
  type NewBotForm,
} from "../features/bots/BotCreateStudio";
import {
  botIdentity,
  createEngineBot,
  deleteEngineBot,
  listEngineBots,
  mergeEngineBots,
  startEngineBot,
} from "../features/bots/api";
import type {
  AssistantConfig,
  AssistantResult,
} from "../features/assistant/ParamAssistantPanel";
import { ApiError } from "../lib/api";
import type { Bot } from "../types";
import CoinLogo, { splitTradingSymbol } from "./coin/CoinLogo";
import LiveValue from "./live/LiveValue";

interface BotsTabProps {
  bots: Bot[];
  setBots: Dispatch<SetStateAction<Bot[]>>;
  availableUSDT: number;
  onOpenBot?: (botId: number) => void;
  onStudioOpenChange?: (open: boolean) => void;
  templateDraft?: { id: number; params: Record<string, unknown> } | null;
}

interface DeleteTarget {
  id: number;
  symbol: string;
}

type SortDirection = "desc" | "asc";

interface CreationFeedback {
  botId: number;
  symbol: string;
  phase: "starting" | "success";
}

const INITIAL_FORM: NewBotForm = {
  symbol: "BTCUSDT",
  budget_usd: 1000,
  dynamic_mode: false,
  base_pct: 50,
  quote_pct: 50,
  upTrail: 0.5,
  upGrids: [
    { trigger_pct: 0.5, qty_pct: 50 },
    { trigger_pct: 1, qty_pct: 50 },
  ],
  downTrail: 0.5,
  downGrids: [
    { trigger_pct: 0.5, qty_pct: 50 },
    { trigger_pct: 1, qty_pct: 50 },
  ],
  maxBuyLevels: 2,
  rebuyTrigger: 1.5,
  rebuyTrail: 0.3,
  resellTrigger: 1.5,
  resellTrail: 0.5,
};

function finite(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function money(value: unknown): string {
  const numeric = finite(value);
  return new Intl.NumberFormat("tr-TR", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(numeric);
}

function percent(value: unknown): string {
  const numeric = finite(value);
  return `${numeric > 0 ? "+" : ""}${numeric.toFixed(2)}%`;
}

function normalizeGrid(
  value: unknown,
  fallback: GridDraft[],
): GridDraft[] {
  if (!Array.isArray(value) || value.length === 0) return fallback;
  return value.slice(0, 20).map((item, index) => {
    const raw = item && typeof item === "object"
      ? item as Record<string, unknown>
      : {};
    return {
      trigger_pct: finite(raw.trigger_pct, (index + 1) * 0.5),
      qty_pct: finite(raw.qty_pct, 100 / value.length),
    };
  });
}

function gridTotal(grids: GridDraft[]): number {
  return grids.reduce((sum, grid) => sum + finite(grid.qty_pct), 0);
}

function validateForm(
  form: NewBotForm,
  availableUSDT: number,
  throughStep = 5,
): string {
  if (throughStep >= 1) {
    if (!/^[A-Z0-9]{5,24}$/.test(form.symbol.trim().toUpperCase())) {
      return "İşlem çifti yalnız harf ve rakamlardan oluşmalı; örneğin BTCUSDT.";
    }
    if (!Number.isFinite(form.budget_usd) || form.budget_usd < 10) {
      return "Bot sermayesi en az 10 USDT olmalıdır.";
    }
    const { quote } = splitTradingSymbol(form.symbol);
    if (quote !== "USDT") {
      return `${form.symbol} Trade ekranında kullanılabilir; mevcut bot motoru güvenli sermaye takibi için yalnız USDT paritelerinde bot açar.`;
    }
    if (!Number.isFinite(availableUSDT)) {
      return "Cüzdan bakiyesi doğrulanmadan bot oluşturulamaz.";
    }
    if (form.budget_usd > availableUSDT + 0.005) {
      return `Bot sermayesi kullanılabilir bakiyeyi aşıyor. Kullanılabilir: ${money(availableUSDT)}.`;
    }
  }
  if (throughStep >= 2) {
    if (
      !Number.isFinite(form.base_pct) ||
      !Number.isFinite(form.quote_pct) ||
      form.base_pct < 0 ||
      form.quote_pct < 0 ||
      form.base_pct > 100 ||
      form.quote_pct > 100 ||
      Math.abs(form.base_pct + form.quote_pct - 100) > 0.5
    ) {
      return "Coin ve yedek bakiye dağılımının toplamı %100 olmalıdır.";
    }
  }
  if (throughStep >= 3) {
    const message = validateGridSide(
      "Satış",
      form.upGrids,
      form.upTrail,
      form.budget_usd,
      form.base_pct,
    );
    if (message) return message;
  }
  if (throughStep >= 4) {
    const message = validateGridSide(
      "Alış",
      form.downGrids,
      form.downTrail,
      form.budget_usd,
      form.quote_pct,
    );
    if (message) return message;
    if (
      !Number.isInteger(form.maxBuyLevels) ||
      form.maxBuyLevels < 1 ||
      form.maxBuyLevels > form.downGrids.length
    ) {
      return "Maksimum alış seviyesi, tanımlı alış gridlerinin sınırları içinde olmalıdır.";
    }
  }
  if (throughStep >= 5) {
    const profitValues = [
      form.rebuyTrigger,
      form.rebuyTrail,
      form.resellTrigger,
      form.resellTrail,
    ];
    if (profitValues.some((value) => !Number.isFinite(value) || value <= 0 || value > 100)) {
      return "Kâr döngüsü eşikleri 0 ile 100 arasında pozitif değerler olmalıdır.";
    }
  }
  return "";
}

function validateGridSide(
  label: string,
  grids: GridDraft[],
  trail: number,
  budget: number,
  allocationPct: number,
): string {
  if (grids.length < 1 || grids.length > 20) {
    return `${label} planında 1 ile 20 arasında grid seviyesi bulunmalıdır.`;
  }
  if (!Number.isFinite(trail) || trail <= 0 || trail > 25) {
    return `${label} trailing değeri 0 ile 25 arasında pozitif olmalıdır.`;
  }
  if (
    grids.some(
      (grid) =>
        !Number.isFinite(grid.trigger_pct) ||
        grid.trigger_pct <= 0 ||
        grid.trigger_pct > 100 ||
        !Number.isFinite(grid.qty_pct) ||
        grid.qty_pct <= 0 ||
        grid.qty_pct > 100,
    )
  ) {
    return `${label} gridlerindeki tetik ve pay değerleri pozitif ve %100'ü aşmayacak biçimde olmalıdır.`;
  }
  if (Math.abs(gridTotal(grids) - 100) > 0.5) {
    return `${label} grid paylarının toplamı %100 olmalıdır.`;
  }
  const smallestNotional = Math.min(
    ...grids.map(
      (grid) =>
        budget *
        (allocationPct / 100) *
        0.995 *
        (grid.qty_pct / 100),
    ),
  );
  if (!(smallestNotional > 10)) {
    const smallestShare = Math.min(...grids.map((grid) => grid.qty_pct / 100));
    const requiredBudget =
      smallestShare > 0 && allocationPct > 0
        ? 10.01 / ((allocationPct / 100) * 0.995 * smallestShare)
        : 0;
    return requiredBudget > 0
      ? `${label} kademelerinden biri 10 USDT sınırının altında. Bu dağılım için bütçeyi en az ${money(requiredBudget)} yapın veya kademe payını büyütün.`
      : `${label} planı için ayrılan başlangıç payı yetersiz.`;
  }
  return "";
}

function assistantAllocation(
  config: AssistantConfig,
  key: "base_pct" | "quote_pct",
  fallback: number,
): number {
  const allocation =
    config.allocation && typeof config.allocation === "object"
      ? config.allocation as Record<string, unknown>
      : {};
  const direct =
    key === "base_pct" ? config.base_alloc_pct : config.quote_alloc_pct;
  return finite(direct ?? allocation[key], fallback);
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function formFromTemplate(
  params: Record<string, unknown>,
  current: NewBotForm,
): NewBotForm {
  const allocation = objectValue(params.allocation);
  const up = objectValue(params.up);
  const down = objectValue(params.down);
  const profit = objectValue(params.profit);
  const dynamicMode = objectValue(params.dynamic_mode);
  const sellLegacy = Array.isArray(params.sell_grids)
    ? params.sell_grids.map((value) => {
        const row = objectValue(value);
        return {
          trigger_pct: finite(row.sell_grid_pct ?? row.trigger_pct),
          qty_pct: finite(row.sell_qty_pct_of_base ?? row.qty_pct),
        };
      })
    : [];
  const buyLegacy = Array.isArray(params.buy_grids)
    ? params.buy_grids.map((value) => {
        const row = objectValue(value);
        return {
          trigger_pct: finite(row.buy_grid_pct ?? row.trigger_pct),
          qty_pct: finite(row.buy_qty_pct_of_quote ?? row.qty_pct),
        };
      })
    : [];
  const upGrids = normalizeGrid(up.grids, sellLegacy.length ? sellLegacy : current.upGrids);
  const downGrids = normalizeGrid(down.grids, buyLegacy.length ? buyLegacy : current.downGrids);
  return {
    ...current,
    symbol: String(params.symbol || current.symbol).trim().toUpperCase(),
    budget_usd: 0,
    dynamic_mode:
      params.dynamic_mode === true ||
      (Object.keys(dynamicMode).length > 0 && dynamicMode.enabled !== false),
    base_pct: finite(params.base_alloc_pct ?? allocation.base_pct, current.base_pct),
    quote_pct: finite(params.quote_alloc_pct ?? allocation.quote_pct, current.quote_pct),
    upTrail: finite(up.trail_pct ?? params.sell_trigger_trailing_pct, current.upTrail),
    upGrids,
    downTrail: finite(down.trail_pct ?? params.buy_trigger_trailing_pct, current.downTrail),
    downGrids,
    maxBuyLevels: Math.min(
      downGrids.length,
      Math.max(1, finite(params.max_buy_levels, downGrids.length)),
    ),
    rebuyTrigger: finite(
      profit.rebuy_trigger_pct ?? params.profit_reentry_drop_pct,
      current.rebuyTrigger,
    ),
    rebuyTrail: finite(
      profit.rebuy_trail_pct ?? params.profit_reentry_rise_pct,
      current.rebuyTrail,
    ),
    resellTrigger: finite(
      profit.resell_trigger_pct ?? params.profit_exit_rise_pct,
      current.resellTrigger,
    ),
    resellTrail: finite(
      profit.resell_trail_pct ?? params.profit_exit_drop_pct,
      current.resellTrail,
    ),
  };
}

export default function BotsTab({
  bots,
  setBots,
  availableUSDT,
  onOpenBot,
  onStudioOpenChange,
  templateDraft,
}: BotsTabProps) {
  const { accountId } = useDashboard();
  const [showCreateStudio, setShowCreateStudio] = useState(false);
  const [currentStep, setCurrentStep] = useState(1);
  const [wizardError, setWizardError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionNotice, setActionNotice] = useState("");
  const [pendingMutations, setPendingMutations] = useState<Set<string>>(
    () => new Set(),
  );
  const [uncertainBotIds, setUncertainBotIds] = useState<Set<number>>(
    () => new Set(),
  );
  const [createRequiresReview, setCreateRequiresReview] = useState(false);
  const [serverListReady, setServerListReady] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [creationFeedback, setCreationFeedback] =
    useState<CreationFeedback | null>(null);
  const [creationFeedbackLeaving, setCreationFeedbackLeaving] = useState(false);
  const [suppressedBotIds, setSuppressedBotIds] = useState<Set<number>>(
    () => new Set(),
  );
  const suppressedBotIdsRef = useRef(new Set<number>());
  const mutationLocksRef = useRef(new Set<string>());
  const [assistantConfig, setAssistantConfig] =
    useState<AssistantConfig | null>(null);
  const [assistantResult, setAssistantResult] =
    useState<AssistantResult | null>(null);
  const [form, setForm] = useState<NewBotForm>(INITIAL_FORM);

  useEffect(() => {
    onStudioOpenChange?.(showCreateStudio);
  }, [onStudioOpenChange, showCreateStudio]);

  useEffect(
    () => () => {
      onStudioOpenChange?.(false);
    },
    [onStudioOpenChange],
  );

  useEffect(() => {
    if (!templateDraft) return;
    setForm((current) => formFromTemplate(templateDraft.params, current));
    setWizardError("");
    setCurrentStep(1);
    clearAssistant();
    setShowCreateStudio(true);
  }, [templateDraft?.id]);

  const lockMutation = (key: string): boolean => {
    if (mutationLocksRef.current.has(key)) return false;
    mutationLocksRef.current.add(key);
    setPendingMutations((current) => new Set(current).add(key));
    return true;
  };

  const unlockMutation = (key: string) => {
    mutationLocksRef.current.delete(key);
    setPendingMutations((current) => {
      const next = new Set(current);
      next.delete(key);
      return next;
    });
  };

  const refreshBotsFromEngine = async (): Promise<boolean> => {
    try {
      const serverBots = await listEngineBots(accountId);
      const visibleServerBots = serverBots.filter(
        (bot) => !suppressedBotIdsRef.current.has(bot.bot_id),
      );
      setBots((current) => mergeEngineBots(visibleServerBots, current));
      setServerListReady(true);
      return true;
    } catch {
      return false;
    }
  };

  useEffect(() => {
    if (!creationFeedback || creationFeedback.phase !== "starting") return;
    void refreshBotsFromEngine();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        void refreshBotsFromEngine();
      }
    }, 1_000);
    return () => window.clearInterval(timer);
  }, [accountId, creationFeedback?.botId, creationFeedback?.phase]);

  useEffect(() => {
    if (!creationFeedback || creationFeedback.phase !== "starting") return;
    const createdBot = bots.find(
      (bot) => botIdentity(bot) === creationFeedback.botId,
    );
    const status = String(
      createdBot?.display_status || createdBot?.status || "",
    ).toLowerCase();
    if (status !== "running") return;
    setCreationFeedback((current) =>
      current && current.botId === creationFeedback.botId
        ? { ...current, phase: "success" }
        : current,
    );
  }, [bots, creationFeedback]);

  useEffect(() => {
    if (!creationFeedback || creationFeedback.phase !== "success") return;
    setCreationFeedbackLeaving(false);
    const fadeTimer = window.setTimeout(
      () => setCreationFeedbackLeaving(true),
      3_000,
    );
    const removeTimer = window.setTimeout(() => {
      setCreationFeedback(null);
      setCreationFeedbackLeaving(false);
    }, 3_600);
    return () => {
      window.clearTimeout(fadeTimer);
      window.clearTimeout(removeTimer);
    };
  }, [creationFeedback?.botId, creationFeedback?.phase]);

  useEffect(() => {
    setServerListReady(false);
    suppressedBotIdsRef.current.clear();
    setSuppressedBotIds(new Set());
    void refreshBotsFromEngine();
  }, [accountId]);

  useEffect(() => {
    const onManualRefresh = () => void refreshBotsFromEngine();
    window.addEventListener("ayserose:manual-refresh", onManualRefresh);
    return () => window.removeEventListener("ayserose:manual-refresh", onManualRefresh);
  }, [accountId]);

  useEffect(() => {
    const onBotDeleted = (event: Event) => {
      const detail = (event as CustomEvent<{
        accountId?: number;
        botId?: number;
      }>).detail;
      const deletedAccountId = Number(detail?.accountId);
      const deletedBotId = Number(detail?.botId);
      if (
        deletedAccountId !== accountId ||
        !Number.isInteger(deletedBotId) ||
        deletedBotId <= 0
      ) {
        return;
      }
      suppressedBotIdsRef.current.add(deletedBotId);
      setSuppressedBotIds((current) => new Set(current).add(deletedBotId));
    };
    window.addEventListener("ayserose:bot-deleted", onBotDeleted);
    return () => window.removeEventListener("ayserose:bot-deleted", onBotDeleted);
  }, [accountId]);

  const isUnknownOutcome = (error: unknown) =>
    error instanceof ApiError &&
    ["timeout", "network", "server", "unknown"].includes(error.kind);

  const clearAssistant = () => {
    setAssistantConfig(null);
    setAssistantResult(null);
  };

  const changeForm = (patch: Partial<NewBotForm>) => {
    setForm((current) => ({ ...current, ...patch }));
  };

  const changeGrid = (
    side: "up" | "down",
    index: number,
    patch: Partial<GridDraft>,
  ) => {
    setForm((current) => {
      const key = side === "up" ? "upGrids" : "downGrids";
      const grids = current[key].map((grid, gridIndex) =>
        gridIndex === index ? { ...grid, ...patch } : grid,
      );
      return { ...current, [key]: grids };
    });
  };

  const changeGridCount = (side: "up" | "down", count: number) => {
    setForm((current) => {
      const key = side === "up" ? "upGrids" : "downGrids";
      const previous = current[key];
      const next = Array.from({ length: count }, (_, index) => ({
        trigger_pct: previous[index]?.trigger_pct ?? (index + 1) * 0.5,
        qty_pct: Number((100 / count).toFixed(4)),
      }));
      return {
        ...current,
        [key]: next,
        ...(side === "down"
          ? { maxBuyLevels: Math.min(current.maxBuyLevels, count) }
          : {}),
      };
    });
  };

  const reviewUncertainMutations = async () => {
    setActionError("");
    const refreshed = await refreshBotsFromEngine();
    if (!refreshed) {
      setActionError("Sunucu durumu doğrulanamadı. Riskli komutlar kapalı tutuluyor.");
      return;
    }
    setUncertainBotIds(new Set());
    setCreateRequiresReview(false);
    setActionNotice("Bot durumları sunucudan yeniden doğrulandı.");
  };

  const handleDeleteBot = async (convertBaseToQuote: boolean) => {
    if (!deleteTarget) return;
    const { id, symbol } = deleteTarget;
    const lockKey = `bot:${id}`;
    if (!lockMutation(lockKey)) return;
    setActionError("");
    setActionNotice("");
    try {
      const response = await deleteEngineBot(accountId, id, convertBaseToQuote);
      suppressedBotIdsRef.current.add(id);
      setSuppressedBotIds((current) => new Set(current).add(id));
      setBots((current) => current.filter((bot) => botIdentity(bot) !== id));
      window.dispatchEvent(
        new CustomEvent("ayserose:bot-deleted", {
          detail: { accountId, botId: id },
        }),
      );
      setDeleteTarget(null);
      setActionNotice(
        response.message ||
          (convertBaseToQuote
            ? `${symbol} varlığı quote bakiyeye dönüştürülerek silme emri alındı.`
            : `${symbol} varlığı korunarak bot silme emri alındı.`),
      );
      void refreshBotsFromEngine();
    } catch (error) {
      if (isUnknownOutcome(error)) {
        await refreshBotsFromEngine();
        setUncertainBotIds((current) => new Set(current).add(id));
        setDeleteTarget(null);
        setActionError(
          "Silme sonucu kesinleşmedi. Yeniden silmeden önce sunucu durumunu doğrulayın.",
        );
        return;
      }
      setActionError(error instanceof Error ? error.message : "Bot silinemedi.");
    } finally {
      unlockMutation(lockKey);
    }
  };

  const handleNextStep = () => {
    const error = validateForm(form, availableUSDT, currentStep);
    if (error) {
      setWizardError(error);
      return;
    }
    setWizardError("");
    setCurrentStep((current) => Math.min(5, current + 1));
  };

  const handleAssistantApply = (
    config: AssistantConfig,
    result: AssistantResult,
  ) => {
    setAssistantConfig(config);
    setAssistantResult(result);
    setForm((current) => {
      const upGrids = normalizeGrid(config.up?.grids, current.upGrids);
      const downGrids = normalizeGrid(config.down?.grids, current.downGrids);
      return {
        ...current,
        base_pct: assistantAllocation(config, "base_pct", current.base_pct),
        quote_pct: assistantAllocation(config, "quote_pct", current.quote_pct),
        upTrail: finite(config.up?.trail_pct, current.upTrail),
        upGrids,
        downTrail: finite(config.down?.trail_pct, current.downTrail),
        downGrids,
        maxBuyLevels: Math.min(
          downGrids.length,
          Math.max(1, finite(config.max_buy_levels, current.maxBuyLevels)),
        ),
        rebuyTrigger: finite(
          config.profit?.rebuy_trigger_pct,
          current.rebuyTrigger,
        ),
        rebuyTrail: finite(config.profit?.rebuy_trail_pct, current.rebuyTrail),
        resellTrigger: finite(
          config.profit?.resell_trigger_pct,
          current.resellTrigger,
        ),
        resellTrail: finite(
          config.profit?.resell_trail_pct,
          current.resellTrail,
        ),
      };
    });
    setWizardError("");
  };

  const buildPayload = (): Record<string, unknown> => {
    const core = {
      symbol: form.symbol.trim().toUpperCase(),
      strategy_id: "dca_grid_trailing",
      budget_usd: form.budget_usd,
      initial_capital_usdt: form.budget_usd,
      base_alloc_pct: form.base_pct,
      quote_alloc_pct: form.quote_pct,
      allocation: { base_pct: form.base_pct, quote_pct: form.quote_pct },
      up: {
        trail_pct: form.upTrail,
        grids: form.upGrids.map((grid) => ({ ...grid })),
      },
      down: {
        trail_pct: form.downTrail,
        grids: form.downGrids.map((grid) => ({ ...grid })),
      },
      max_buy_levels: form.maxBuyLevels,
      profit: {
        rebuy_trigger_pct: form.rebuyTrigger,
        rebuy_trail_pct: form.rebuyTrail,
        resell_trigger_pct: form.resellTrigger,
        resell_trail_pct: form.resellTrail,
      },
      dynamic_mode: form.dynamic_mode,
      daily_loss_limit_usd: 0,
    };
    if (!assistantConfig || !assistantResult) return core;
    const decision =
      String(assistantResult.decision ?? assistantResult.final_action ?? "");
    return {
      ...assistantConfig,
      ...core,
      allocation: {
        ...(assistantConfig.allocation &&
        typeof assistantConfig.allocation === "object"
          ? assistantConfig.allocation as Record<string, unknown>
          : {}),
        ...core.allocation,
      },
      up: { ...assistantConfig.up, ...core.up },
      down: { ...assistantConfig.down, ...core.down },
      profit: { ...assistantConfig.profit, ...core.profit },
      config_source: "param_assistant",
      param_assistant_job_id: assistantResult.job_id,
      param_assistant_decision: decision,
      param_assistant_confidence: assistantResult.confidence,
      param_assistant: {
        source: "frontend_v2_param_assistant",
        job_id: assistantResult.job_id,
        decision_id: assistantResult.decision_id,
        decision,
        confidence: assistantResult.confidence,
        template_key: assistantResult.template_key,
        param_score: assistantResult.param_score,
        regime_tag: assistantResult.regime_tag,
        display_regime_label: assistantResult.display_regime_label,
        market_status_plain: assistantResult.market_status_plain,
        symbol: core.symbol,
      },
    };
  };

  const handleCreateBot = async () => {
    const validationError = validateForm(form, availableUSDT, 5);
    if (validationError) {
      setWizardError(validationError);
      return;
    }
    if (!serverListReady) {
      setWizardError("Bot listesi sunucudan doğrulanmadan yeni bot oluşturulamaz.");
      return;
    }
    const lockKey = "create";
    if (!lockMutation(lockKey)) return;
    const payload = buildPayload();
    let createdBotId: number | null = null;
    setWizardError("");
    setActionError("");
    setActionNotice("");
    setCreationFeedback(null);
    setCreationFeedbackLeaving(false);
    try {
      const created = await createEngineBot(accountId, payload);
      createdBotId = created.bot_id;
      setBots((current) => {
        const [optimisticBot] = mergeEngineBots(
          [
            {
              bot_id: created.bot_id,
              bot_code: created.bot_code,
              account_id: created.account_id,
              symbol: created.symbol,
              status: "running",
              display_status: "starting",
              initial_allocation_done: false,
              config: payload,
            },
          ],
          current,
        );
        return [
          optimisticBot,
          ...current.filter((bot) => botIdentity(bot) !== created.bot_id),
        ];
      });
      await startEngineBot(accountId, created.bot_id);
      setCreationFeedback({
        botId: created.bot_id,
        symbol: created.symbol || form.symbol,
        phase: "starting",
      });
      setShowCreateStudio(false);
      setCurrentStep(1);
      clearAssistant();
      void refreshBotsFromEngine();
    } catch (error) {
      setCreationFeedback(null);
      if (createdBotId !== null) await refreshBotsFromEngine();
      if (isUnknownOutcome(error)) {
        await refreshBotsFromEngine();
        setCreateRequiresReview(true);
        setWizardError(
          "Oluşturma veya başlatma yanıtı kesinleşmedi. Tekrar denemeden önce sunucu durumunu doğrulayın.",
        );
        return;
      }
      const message = error instanceof Error ? error.message : "Bot oluşturulamadı.";
      setWizardError(
        createdBotId === null
          ? message
          : `Bot oluşturuldu fakat başlatma kuyruğuna alınamadı. Bot durmuş halde korunuyor: ${message}`,
      );
    } finally {
      unlockMutation(lockKey);
    }
  };

  const openStudio = () => {
    setWizardError("");
    setCurrentStep(1);
    clearAssistant();
    setShowCreateStudio(true);
  };

  const visibleBots = useMemo(() => {
    const next = bots.filter(
      (bot) => !suppressedBotIds.has(botIdentity(bot)),
    );
    return [...next].sort((left, right) => {
      const gainDifference =
        finite(right.total_pnl_pct) - finite(left.total_pnl_pct);
      if (gainDifference !== 0) {
        return sortDirection === "desc" ? gainDifference : -gainDifference;
      }
      return sortDirection === "desc"
        ? botIdentity(right) - botIdentity(left)
        : botIdentity(left) - botIdentity(right);
    });
  }, [bots, sortDirection, suppressedBotIds]);

  return (
    <section className="mx-auto max-w-6xl space-y-5">
      <header className="relative overflow-hidden rounded-[1.75rem] border border-fuchsia-300/15 bg-[#191a21] p-5 sm:p-7">
        <div className="pointer-events-none absolute -right-20 -top-24 h-72 w-72 rounded-full bg-fuchsia-400/10 blur-3xl" />
        <div className="relative flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.22em] text-fuchsia-200">
              <Sparkles className="h-4 w-4" />
              Strateji kontrol merkezi
            </p>
            <h1 className="mt-3 text-3xl font-black tracking-[-0.035em] text-white sm:text-4xl">
              Botlarını tek bakışta yönet.
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-neutral-400">
              Canlı durum, motor sağlığı ve performans aynı yüzeyde. Yeni bot
              stüdyosu backendin gerçek Trailing DCA sözleşmesini eksiksiz uygular.
            </p>
          </div>
          <button
            type="button"
            onClick={openStudio}
            disabled={createRequiresReview || !serverListReady}
            className="inline-flex h-12 shrink-0 items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-fuchsia-300 to-violet-300 px-5 text-xs font-black text-neutral-950 shadow-[0_14px_40px_rgba(212,148,236,.15)] transition hover:brightness-110 disabled:cursor-not-allowed disabled:grayscale disabled:opacity-50"
          >
            <Plus className="h-4 w-4" />
            Yeni bot tasarla
          </button>
        </div>
      </header>

      {(createRequiresReview || uncertainBotIds.size > 0) && (
        <Notice tone="warning">
          <span>
            Bir komutun sonucu kesinleşmedi. Yeni riskli işlem göndermeden önce
            motor durumunu yeniden doğrulayın.
          </span>
          <button
            type="button"
            onClick={() => void reviewUncertainMutations()}
            className="inline-flex shrink-0 items-center gap-2 rounded-xl border border-amber-300/25 px-3 py-2 text-xs font-black text-amber-100"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Sunucuyu doğrula
          </button>
        </Notice>
      )}

      {actionError && (
        <div role="alert" className="flex items-start gap-2 rounded-2xl border border-red-400/20 bg-red-400/[0.06] p-4 text-sm leading-6 text-red-100">
          <AlertTriangle className="mt-1 h-4 w-4 shrink-0" />
          {actionError}
        </div>
      )}
      {creationFeedback && (
        <div
          role="status"
          aria-live="polite"
          className={`flex items-center gap-3 rounded-2xl border p-4 text-sm font-bold transition-all duration-500 ${
            creationFeedback.phase === "success"
              ? "border-emerald-300/15 bg-emerald-300/[0.055] text-emerald-100"
              : "border-fuchsia-300/15 bg-fuchsia-300/[0.055] text-fuchsia-100"
          } ${
            creationFeedbackLeaving
              ? "translate-y-1 opacity-0"
              : "translate-y-0 opacity-100"
          }`}
        >
          {creationFeedback.phase === "success" ? (
            <Sparkles className="h-4 w-4 shrink-0 text-emerald-200" />
          ) : (
            <LoaderCircle className="h-4 w-4 shrink-0 animate-spin text-fuchsia-200" />
          )}
          {creationFeedback.phase === "success"
            ? `${splitTradingSymbol(creationFeedback.symbol).label} botunuz başarıyla çalıştırıldı.`
            : "Botunuz oluşturuluyor."}
        </div>
      )}
      {actionNotice && (
        <div role="status" className="rounded-2xl border border-emerald-300/15 bg-emerald-300/[0.05] p-4 text-sm text-emerald-100">
          {actionNotice}
        </div>
      )}

      {visibleBots.length > 1 && (
        <div className="flex justify-end">
          <button
            type="button"
            aria-label={
              sortDirection === "desc"
                ? "En yüksek performans üstte; en düşüğü üste almak için dokun"
                : "En düşük performans üstte; en yükseği üste almak için dokun"
            }
            title={
              sortDirection === "desc"
                ? "Tüm zamanlar · En yüksek üstte"
                : "Tüm zamanlar · En düşük üstte"
            }
            onClick={() =>
              setSortDirection((current) =>
                current === "desc" ? "asc" : "desc",
              )
            }
            className={`inline-grid h-11 w-11 place-items-center rounded-xl border transition ${
              sortDirection === "desc"
                ? "border-emerald-300/25 bg-emerald-300/[0.08] text-emerald-300"
                : "border-red-300/25 bg-red-300/[0.08] text-red-300"
            }`}
          >
            {sortDirection === "desc" ? (
              <ArrowUp className="h-5 w-5" />
            ) : (
              <ArrowDown className="h-5 w-5" />
            )}
          </button>
        </div>
      )}

      {visibleBots.length === 0 && !serverListReady ? (
        <div
          role="status"
          className="grid min-h-52 place-items-center rounded-[1.75rem] border border-white/8 bg-[#191a20] p-8 text-center"
        >
          <div>
            <LoaderCircle className="mx-auto h-7 w-7 animate-spin text-fuchsia-200" />
            <p className="mt-3 text-sm font-bold text-neutral-400">Botlar hazırlanıyor…</p>
          </div>
        </div>
      ) : visibleBots.length === 0 ? (
        <div className="grid min-h-80 place-items-center rounded-[1.75rem] border border-dashed border-fuchsia-300/15 bg-[#191a20] p-8 text-center">
          <div className="max-w-md">
            <span className="mx-auto grid h-16 w-16 place-items-center rounded-2xl border border-fuchsia-300/15 bg-fuchsia-300/[0.06] text-fuchsia-100">
              <BotIcon className="h-7 w-7" />
            </span>
            <h2 className="mt-5 text-xl font-black text-white">İlk stratejin için alan hazır</h2>
            <p className="mt-2 text-sm leading-6 text-neutral-500">
              Bütçe, grid ve trailing kararlarını görünür tutan bot stüdyosuyla başla.
            </p>
            <button
              type="button"
              onClick={openStudio}
              className="mt-5 inline-flex items-center gap-2 rounded-xl bg-fuchsia-200 px-4 py-3 text-xs font-black text-neutral-950"
            >
              <Plus className="h-4 w-4" />
              İlk botu tasarla
            </button>
          </div>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {visibleBots.map((bot) => {
            const id = botIdentity(bot);
            const isPending = pendingMutations.has(`bot:${id}`);
            const needsReview = uncertainBotIds.has(id);
            const status = botStatus(bot);
            const isRunning = ["running", "starting", "waiting"].includes(status.key);
            const pair = splitTradingSymbol(bot.symbol);
            const pnl = finite(bot.total_pnl_pct);
            const hasAlert =
              Boolean(bot.health_alert_level) ||
              Boolean(bot.health_alerts?.length);
            return (
              <article
                key={id}
                className="group overflow-hidden rounded-[1.5rem] border border-white/8 bg-[#191a20] shadow-[0_20px_70px_rgba(0,0,0,.2)] transition hover:-translate-y-0.5 hover:border-fuchsia-300/18"
              >
                <div className="border-b border-white/8 p-5">
                  <div className="flex items-start justify-between gap-3">
                    <button
                      type="button"
                      onClick={() => onOpenBot?.(id)}
                      className="flex min-w-0 items-center gap-3 text-left"
                    >
                      <CoinLogo symbol={bot.symbol} size={46} />
                      <span className="min-w-0">
                        <span className="block truncate text-base font-black text-white">{pair.label}</span>
                      </span>
                    </button>
                    <span className={`shrink-0 rounded-full px-2.5 py-1 text-[10px] font-black ${status.className}`}>
                      {status.label}
                    </span>
                  </div>
                  {(hasAlert || needsReview) && (
                    <div className="mt-4 flex items-center gap-2 rounded-xl border border-amber-300/15 bg-amber-300/[0.05] px-3 py-2 text-[11px] font-bold text-amber-100">
                      <ShieldAlert className="h-3.5 w-3.5 shrink-0" />
                      {needsReview
                        ? "Komut sonucu doğrulama bekliyor"
                        : `${bot.health_alerts?.length || 1} motor uyarısı`}
                    </div>
                  )}
                </div>

                <div className="mx-4 mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-xl bg-white/6">
                  <MetricTile
                    icon={CircleDollarSign}
                    label="Bot değeri"
                    value={money(bot.current_usd)}
                    liveValue={bot.current_usd}
                  />
                  <MetricTile
                    icon={WalletCards}
                    label="Başlangıç"
                    value={money(bot.budget_usd)}
                  />
                  <MetricTile
                    icon={Layers3}
                    label="Aktif tur"
                    value={String(
                      finite(
                        bot.cycle_id,
                        finite(bot.total_cycles_completed) + (isRunning ? 1 : 0),
                      ),
                    )}
                  />
                  <MetricTile
                    icon={Sparkles}
                    label="Toplam performans"
                    value={percent(pnl)}
                    valueClass={pnl >= 0 ? "text-emerald-300" : "text-red-300"}
                    liveValue={pnl}
                  />
                </div>

                <footer className="p-4">
                  <button
                    type="button"
                    onClick={() => onOpenBot?.(id)}
                    className="inline-flex h-14 w-full items-center justify-center gap-2 rounded-2xl border border-fuchsia-300/20 bg-gradient-to-r from-fuchsia-300/[0.14] to-violet-300/[0.09] text-sm font-black text-white shadow-[0_10px_28px_rgba(198,125,236,.08)] transition hover:border-fuchsia-300/35 hover:from-fuchsia-300/[0.19] hover:to-violet-300/[0.13]"
                  >
                    Detayı aç
                    <ArrowRight className="h-3.5 w-3.5" />
                  </button>
                </footer>
              </article>
            );
          })}
        </div>
      )}

      {showCreateStudio && typeof document !== "undefined" && createPortal(
        <BotCreateStudio
          form={form}
          step={currentStep}
          availableUSDT={availableUSDT}
          error={wizardError}
          isCreating={pendingMutations.has("create")}
          disabled={createRequiresReview || !serverListReady}
          assistantApplied={Boolean(assistantConfig)}
          assistantResult={assistantResult}
          onClose={() => {
            if (!pendingMutations.has("create")) setShowCreateStudio(false);
          }}
          onChange={changeForm}
          onGridChange={changeGrid}
          onGridCountChange={changeGridCount}
          onAssistantApply={handleAssistantApply}
          onPrevious={() => {
            setWizardError("");
            setCurrentStep((current) => Math.max(1, current - 1));
          }}
          onNext={handleNextStep}
          onSubmit={() => void handleCreateBot()}
        />,
        document.body,
      )}

      {deleteTarget && (
        <DeleteBotDialog
          target={deleteTarget}
          pending={pendingMutations.has(`bot:${deleteTarget.id}`)}
          onCancel={() => setDeleteTarget(null)}
          onDelete={(convert) => void handleDeleteBot(convert)}
        />
      )}
    </section>
  );
}

function botStatus(bot: Bot): {
  key: string;
  label: string;
  className: string;
} {
  const raw = String(bot.display_status || bot.status || "").toLowerCase();
  if (raw.includes("error") || raw.includes("fail")) {
    return { key: "error", label: "Hata", className: "bg-red-300/10 text-red-200" };
  }
  if (raw === "starting") {
    return { key: "starting", label: "Başlatılıyor", className: "bg-sky-300/10 text-sky-200" };
  }
  if (raw === "stopping") {
    return { key: "stopping", label: "Durduruluyor", className: "bg-amber-300/10 text-amber-200" };
  }
  if (raw === "running" && bot.initial_allocation_done === false) {
    return { key: "waiting", label: "İlk alım bekliyor", className: "bg-violet-300/10 text-violet-200" };
  }
  if (raw === "running") {
    return { key: "running", label: "Çalışıyor", className: "bg-emerald-300/10 text-emerald-200" };
  }
  return { key: "stopped", label: "Durduruldu", className: "bg-white/5 text-neutral-400" };
}

function Notice({
  tone,
  children,
}: {
  tone: "warning" | "neutral";
  children: ReactNode;
}) {
  return (
    <div
      className={`flex flex-col gap-3 rounded-2xl border p-4 text-sm leading-6 sm:flex-row sm:items-center sm:justify-between ${
        tone === "warning"
          ? "border-amber-300/20 bg-amber-300/[0.05] text-amber-100"
          : "border-white/10 bg-white/[0.025] text-neutral-400"
      }`}
    >
      {children}
    </div>
  );
}

function MetricTile({
  icon: Icon,
  label,
  value,
  valueClass = "",
  liveValue,
}: {
  icon: typeof CircleDollarSign;
  label: string;
  value: string;
  valueClass?: string;
  liveValue?: unknown;
}) {
  return (
    <div className="bg-[#191a20] p-4">
      <p className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-neutral-600">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </p>
      <p className={`mt-2 truncate text-sm font-black text-white ${valueClass}`}>
        {liveValue !== undefined ? (
          <LiveValue value={liveValue}>{value}</LiveValue>
        ) : (
          value
        )}
      </p>
    </div>
  );
}

function DeleteBotDialog({
  target,
  pending,
  onCancel,
  onDelete,
}: {
  target: DeleteTarget;
  pending: boolean;
  onCancel: () => void;
  onDelete: (convert: boolean) => void;
}) {
  const pair = splitTradingSymbol(target.symbol);
  return (
    <div className="fixed inset-0 z-[60] grid place-items-center bg-black/80 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="delete-bot-title">
      <section className="w-full max-w-lg overflow-hidden rounded-[1.5rem] border border-red-300/15 bg-[#191a20] shadow-2xl">
        <header className="flex items-start justify-between gap-4 border-b border-white/8 p-5">
          <div className="flex items-center gap-3">
            <CoinLogo symbol={target.symbol} size={46} eager />
            <div>
              <p className="text-[10px] font-black uppercase tracking-wider text-red-200">Kalıcı işlem</p>
              <h2 id="delete-bot-title" className="mt-1 text-lg font-black text-white">
                {pair.label} botunu sil
              </h2>
            </div>
          </div>
          <button type="button" onClick={onCancel} disabled={pending} aria-label="Silme penceresini kapat" className="grid h-9 w-9 place-items-center rounded-xl text-neutral-500 hover:bg-white/5 hover:text-white disabled:opacity-40">
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="space-y-3 p-5">
          <p className="text-sm leading-6 text-neutral-400">
            Bot silinirken eldeki <strong className="text-white">{pair.base}</strong> varlığının
            ne olacağını seçin. Bu karar bakiye davranışını doğrudan etkiler.
          </p>
          <button
            type="button"
            onClick={() => onDelete(true)}
            disabled={pending}
            className="w-full rounded-2xl border border-red-300/15 bg-red-300/[0.05] p-4 text-left transition hover:bg-red-300/[0.08] disabled:opacity-40"
          >
            <span className="block text-sm font-black text-red-100">Varlığı USDT'ye çevir ve sil</span>
            <span className="mt-1 block text-xs leading-5 text-neutral-500">Eldeki base varlık piyasa emriyle quote bakiyeye dönüştürülür.</span>
          </button>
          <button
            type="button"
            onClick={() => onDelete(false)}
            disabled={pending}
            className="w-full rounded-2xl border border-white/10 bg-white/[0.025] p-4 text-left transition hover:bg-white/[0.05] disabled:opacity-40"
          >
            <span className="block text-sm font-black text-white">Varlığı cüzdanda bırak ve sil</span>
            <span className="mt-1 block text-xs leading-5 text-neutral-500">Satış yapılmaz; mevcut coin bakiyesi aynen korunur.</span>
          </button>
          {pending && (
            <p className="flex items-center justify-center gap-2 pt-1 text-xs font-bold text-neutral-400">
              <LoaderCircle className="h-4 w-4 animate-spin" />
              Motor yanıtı bekleniyor…
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
