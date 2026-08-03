export type DecimalInput = string | number;

interface DecimalParts {
  units: bigint;
  scale: number;
}

const DECIMAL_PATTERN =
  /^([+]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/;
const MAX_SCALE = 40;

function expandDecimal(value: DecimalInput): string | null {
  const source =
    typeof value === "number"
      ? Number.isFinite(value)
        ? String(value)
        : ""
      : value.trim().replace(",", ".");
  if (source.length > 100) return null;
  const match = DECIMAL_PATTERN.exec(source);
  if (!match) return null;

  const integer = match[2] ?? "0";
  const fraction = match[3] ?? match[4] ?? "";
  const exponent = Number.parseInt(match[5] ?? "0", 10);
  if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > MAX_SCALE) {
    return null;
  }

  const digits = `${integer}${fraction}`;
  const decimalIndex = integer.length + exponent;
  let expanded: string;
  if (decimalIndex <= 0) {
    expanded = `0.${"0".repeat(-decimalIndex)}${digits}`;
  } else if (decimalIndex >= digits.length) {
    expanded = `${digits}${"0".repeat(decimalIndex - digits.length)}`;
  } else {
    expanded = `${digits.slice(0, decimalIndex)}.${digits.slice(decimalIndex)}`;
  }

  const [rawInteger, rawFraction = ""] = expanded.split(".");
  const normalizedInteger = rawInteger.replace(/^0+(?=\d)/, "") || "0";
  const normalizedFraction = rawFraction.replace(/0+$/, "");
  if (normalizedFraction.length > MAX_SCALE) return null;
  return normalizedFraction
    ? `${normalizedInteger}.${normalizedFraction}`
    : normalizedInteger;
}

function parseDecimal(value: DecimalInput): DecimalParts | null {
  const normalized = expandDecimal(value);
  if (normalized === null) return null;
  const [integer, fraction = ""] = normalized.split(".");
  return {
    units: BigInt(`${integer}${fraction}`),
    scale: fraction.length,
  };
}

function powerOfTen(exponent: number): bigint {
  return 10n ** BigInt(exponent);
}

function scaleUnits(parts: DecimalParts, scale: number): bigint {
  return parts.units * powerOfTen(scale - parts.scale);
}

function formatUnits(units: bigint, scale: number): string {
  if (scale === 0) return units.toString();
  const digits = units.toString().padStart(scale + 1, "0");
  const integer = digits.slice(0, -scale);
  const fraction = digits.slice(-scale).replace(/0+$/, "");
  return fraction ? `${integer}.${fraction}` : integer;
}

export function normalizeDecimal(value: DecimalInput): string | null {
  return expandDecimal(value);
}

export function isPositiveDecimal(value: DecimalInput): boolean {
  const parts = parseDecimal(value);
  return parts !== null && parts.units > 0n;
}

export function compareDecimal(
  left: DecimalInput,
  right: DecimalInput,
): number | null {
  const leftParts = parseDecimal(left);
  const rightParts = parseDecimal(right);
  if (!leftParts || !rightParts) return null;
  const scale = Math.max(leftParts.scale, rightParts.scale);
  const leftUnits = scaleUnits(leftParts, scale);
  const rightUnits = scaleUnits(rightParts, scale);
  return leftUnits < rightUnits ? -1 : leftUnits > rightUnits ? 1 : 0;
}

/**
 * Rounds a non-negative decimal down to an exchange step without ever
 * converting the value or step to a binary floating-point number.
 */
export function quantizeDown(
  value: DecimalInput,
  step: DecimalInput,
): string | null {
  const valueParts = parseDecimal(value);
  const stepParts = parseDecimal(step);
  if (!valueParts || !stepParts || stepParts.units <= 0n) return null;

  const scale = Math.max(valueParts.scale, stepParts.scale);
  const valueUnits = scaleUnits(valueParts, scale);
  const stepUnits = scaleUnits(stepParts, scale);
  const quantized = (valueUnits / stepUnits) * stepUnits;
  return formatUnits(quantized, scale);
}

export function multiplyDecimal(
  left: DecimalInput,
  right: DecimalInput,
): string | null {
  const leftParts = parseDecimal(left);
  const rightParts = parseDecimal(right);
  if (!leftParts || !rightParts) return null;
  return formatUnits(
    leftParts.units * rightParts.units,
    leftParts.scale + rightParts.scale,
  );
}

export function multiplyByRatio(
  value: DecimalInput,
  numerator: number,
  denominator = 100,
): string | null {
  const parts = parseDecimal(value);
  if (
    !parts ||
    !Number.isSafeInteger(numerator) ||
    !Number.isSafeInteger(denominator) ||
    numerator < 0 ||
    denominator <= 0
  ) {
    return null;
  }
  return formatUnits(
    (parts.units * BigInt(numerator)) / BigInt(denominator),
    parts.scale,
  );
}

/**
 * Computes numerator / denominator and rounds the result down to `step`.
 * The complete division and quantization path uses integer arithmetic.
 */
export function divideAndQuantize(
  numerator: DecimalInput,
  denominator: DecimalInput,
  step: DecimalInput,
): string | null {
  const numeratorParts = parseDecimal(numerator);
  const denominatorParts = parseDecimal(denominator);
  const stepParts = parseDecimal(step);
  if (
    !numeratorParts ||
    !denominatorParts ||
    !stepParts ||
    denominatorParts.units <= 0n ||
    stepParts.units <= 0n
  ) {
    return null;
  }

  const quotientSteps =
    (numeratorParts.units *
      powerOfTen(denominatorParts.scale + stepParts.scale)) /
    (denominatorParts.units *
      stepParts.units *
      powerOfTen(numeratorParts.scale));
  return formatUnits(quotientSteps * stepParts.units, stepParts.scale);
}
