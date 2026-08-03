import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const read = (path) => readFileSync(resolve(root, path), "utf8");
const serviceWorker = read("public/sw.js");
const settings = read("src/features/notifications/PushNotificationSettings.tsx");
const botDetail = read("src/features/bots/BotDetailPage.tsx");
const app = read("src/App.tsx");
const pushBackend = read("../../app/services/web_push_notifications.py");
const pushHandler = serviceWorker.slice(
  serviceWorker.indexOf('self.addEventListener("push"'),
  serviceWorker.indexOf('self.addEventListener("notificationclick"'),
);
const clickHandler = serviceWorker.slice(
  serviceWorker.indexOf('self.addEventListener("notificationclick"'),
);

assert.match(serviceWorker, /addEventListener\("push"/);
assert.match(serviceWorker, /showNotification/);
assert.match(serviceWorker, /addEventListener\("notificationclick"/);
assert.match(serviceWorker, /clients\.openWindow/);
assert.match(serviceWorker, /AYSEROSE_OPEN_BOT_DETAIL/);
assert.doesNotMatch(pushHandler, /postMessage|\.navigate\(|clients\.openWindow/);
assert.match(clickHandler, /postMessage/);
assert.match(serviceWorker, /searchParams\.set\("bot_id"/);
assert.match(app, /AYSEROSE_OPEN_BOT_DETAIL/);
assert.match(app, /setSelectedBotId\(botId\)/);
assert.match(pushBackend, /"bot_id": int\(bot_id\)/);
assert.match(settings, /Notification\.requestPermission\(\)/);
assert.match(settings, /pushManager\.subscribe/);
assert.match(settings, /\/api\/push\/subscriptions/);
assert.doesNotMatch(settings, /registration\.showNotification/);
assert.doesNotMatch(settings, /Test bildirimi/);
assert.doesNotMatch(serviceWorker, /from ayserose/i);
assert.match(settings, /iPhone kilit ekranı bildirimleri desteklenir/);
assert.match(app, /connectionHealthy/);
assert.match(app, /Bağlantı stabil/);
assert.doesNotMatch(app, /Yedek bağlantı/);
assert.match(botDetail, /Çalışma modu/);
assert.match(botDetail, /Aktif tur/);
assert.match(botDetail, /Ana rejim/);

console.log("Web Push notification contract: OK");
