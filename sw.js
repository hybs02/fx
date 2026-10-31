// オフラインでも前回の画面を出すための仕組み（Service Worker）。
// ・画面（HTML）と data.json などは、毎回ネットを先に見る（更新がすぐ届くように）。
//   つながらない時だけ、前回保存した物を出す。
// ・アイコン等の変わらない物は保存した物を先に使う。
const CACHE = "usdjpy-v2";
const SHELL = ["./", "index.html", "manifest.webmanifest", "apple-touch-icon.png", "icon-192.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return;
  const key = e.request.mode === "navigate" ? "index.html" : u.pathname.replace(/^.*\//, "") || "index.html";
  if (e.request.mode === "navigate" || /\.(json|html)$/.test(u.pathname)) {
    e.respondWith(fetch(e.request, {cache: "no-store"}).then(r => {
      if (r.ok) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(key, copy)); }
      return r;
    }).catch(() => caches.match(key)));
    return;
  }
  e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request)));
});

// サインの通知（GitHub Actions の notify.py が送る）。通知を出し、ホーム画面のアイコンに数字を付ける
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = {body: e.data ? e.data.text() : ""}; }
  e.waitUntil(Promise.all([
    self.registration.showNotification(d.title || "ドル円シグナル", {body: d.body || "", icon: "icon-192.png", tag: "usdjpy-signal", data: {url: d.url || "./"}}),
    self.navigator && self.navigator.setAppBadge ? self.navigator.setAppBadge(1).catch(() => {}) : null,
  ]));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({type: "window", includeUncontrolled: true}).then(ws => {
    const w = ws.find(x => "focus" in x);
    return w ? w.focus() : self.clients.openWindow(e.notification.data && e.notification.data.url || "./");
  }));
});
