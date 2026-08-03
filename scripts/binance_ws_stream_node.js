#!/usr/bin/env node
"use strict";

const url = process.argv[2] || "wss://stream.binance.com/stream?streams=!miniTicker@arr";

function write(event) {
  process.stdout.write(JSON.stringify(event) + "\n");
}

async function normalizeMessage(data) {
  if (typeof data === "string") return data;
  if (data instanceof ArrayBuffer) return Buffer.from(data).toString("utf8");
  if (ArrayBuffer.isView(data)) {
    return Buffer.from(data.buffer, data.byteOffset, data.byteLength).toString("utf8");
  }
  if (data && typeof data.text === "function") return await data.text();
  return String(data || "");
}

if (typeof WebSocket !== "function") {
  write({ type: "error", error: "node_websocket_unavailable" });
  process.exit(2);
}

let ws = null;
let closed = false;

function closeGracefully() {
  closed = true;
  try {
    if (ws && ws.readyState < 2) ws.close(1000, "shutdown");
  } catch (_) {}
  setTimeout(() => process.exit(0), 250).unref();
}

process.on("SIGTERM", closeGracefully);
process.on("SIGINT", closeGracefully);

try {
  ws = new WebSocket(url);
  ws.onopen = () => write({ type: "connected", url });
  ws.onerror = (event) => {
    const message = event && event.message ? event.message : "websocket_error";
    write({ type: "error", error: message });
  };
  ws.onclose = (event) => {
    write({
      type: "closed",
      code: event && event.code,
      reason: event && event.reason ? String(event.reason) : "",
      clean: !!(event && event.wasClean),
    });
    if (!closed) process.exit(event && event.wasClean ? 0 : 1);
  };
  ws.onmessage = async (event) => {
    try {
      const raw = await normalizeMessage(event.data);
      if (raw) write({ type: "message", data: raw });
    } catch (error) {
      write({ type: "error", error: error && error.message ? error.message : String(error) });
    }
  };
} catch (error) {
  write({ type: "error", error: error && error.message ? error.message : String(error) });
  process.exit(1);
}
