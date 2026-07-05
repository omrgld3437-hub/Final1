#!/usr/bin/env node
"use strict";

const readline = require("readline");

const DEFAULT_BASE = "https://api.binance.com";

function buildUrl(path, params, base) {
  const url = new URL(path, base || DEFAULT_BASE);
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null) {
      url.searchParams.set(key, String(value));
    }
  }
  return url;
}

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });

rl.on("line", async (line) => {
  let request;
  try {
    request = JSON.parse(line);
  } catch (error) {
    process.stdout.write(JSON.stringify({ id: null, ok: false, error: "invalid_json" }) + "\n");
    return;
  }

  try {
    const response = await fetch(buildUrl(request.path, request.params, request.base), {
      method: "GET",
      headers: { "accept": "application/json" },
    });
    const text = await response.text();
    let data = text;
    try {
      data = JSON.parse(text);
    } catch (_) {
      // Keep text body for diagnostics.
    }
    if (!response.ok) {
      process.stdout.write(JSON.stringify({
        id: request.id,
        ok: false,
        status: response.status,
        error: typeof data === "string" ? data.slice(0, 300) : data,
      }) + "\n");
      return;
    }
    process.stdout.write(JSON.stringify({ id: request.id, ok: true, data }) + "\n");
  } catch (error) {
    process.stdout.write(JSON.stringify({
      id: request.id,
      ok: false,
      error: error && error.message ? error.message : String(error),
    }) + "\n");
  }
});
