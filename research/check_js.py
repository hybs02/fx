# -*- coding: utf-8 -*-
"""logic.py が旧 JS 版（index.html 2026-09-08 版）と同じ答えを出すかの確認。

旧 JS の関数を node で動かし、同じ日足で
  ・毎日の日足スコア
  ・バックテストの取引一覧（全期間・後半30%）
  ・signalDay
を突き合わせる。1 件でも食い違えば止まる。
使い方: python research/check_js.py <旧index.html>
"""
import io, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import legacy_logic as logic  # noqa: E402  旧規則（2026-09-08 版）の Python 移植

old_html = sys.argv[1]
src = io.open(old_html, encoding="utf-8").read()
js = src[src.index("// ===== 指標"):src.index("// ===== ファンダ")]
consts = src[src.index("const WIN_GATE"):src.index("// 資金管理")]

PAIRS = ["USDJPY", "EURUSD", "GBPJPY", "AUDUSD"]
payload = {}
for p in PAIRS:
    d = json.load(io.open(os.path.join(HERE, "cache", f"yahoo_d_{p}.json")))
    n = 1300                       # 旧アプリは日足 1300 本で検証していた
    payload[p] = [{"h": h, "l": l, "c": c} for h, l, c in
                  zip(d["h"][-n - 1:-1], d["l"][-n - 1:-1], d["c"][-n - 1:-1])]

runner = consts + js + r"""
const data = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));
const out = {};
for (const p of Object.keys(data)) {
  const bars = data[p], closes = bars.map(b => b.c);
  const scores = [];
  for (let t = 0; t < closes.length; t++) scores.push(analyze(closes.slice(0, t + 1), closes[t]).score);
  const full = backtest(bars);
  const split = Math.floor(bars.length * 0.7);
  const oos = backtest(bars.slice(split));
  const days = [];
  for (let t = closes.length - 60; t < closes.length; t++) {
    const sub = closes.slice(0, t + 1), sc = analyze(sub, sub[sub.length - 1]).score;
    const d = sc >= ENTRY_GATE ? 1 : (sc <= -ENTRY_GATE ? -1 : 0);
    days.push(signalDay(sub, d));
  }
  out[p] = {scores, full, oos, days};
}
console.log(JSON.stringify(out));
"""
tmp = os.path.join(HERE, "cache", "_check.js")
io.open(tmp, "w", encoding="utf-8").write(runner)
tmpd = os.path.join(HERE, "cache", "_check.json")
io.open(tmpd, "w").write(json.dumps(payload))
res = json.loads(subprocess.run(["node", tmp, tmpd], capture_output=True, text=True, check=True).stdout)

bad = 0
for p in PAIRS:
    bars = payload[p]
    h = [b["h"] for b in bars]; l = [b["l"] for b in bars]; c = [b["c"] for b in bars]
    sc = logic.score_series(c)
    js_sc = res[p]["scores"]
    for t in range(len(c)):
        # JS は 0 本目からスコアを出す（指標が揃わない間は部分点）。Python も同じ
        if sc[t] != js_sc[t]:
            bad += 1
            if bad < 5:
                print("score diff", p, t, sc[t], js_sc[t])
    for name, (o_, h_, l_, c_) in (("full", (None, h, l, c)),
                                   ("oos", (None, h[int(len(c) * 0.7):], l[int(len(c) * 0.7):], c[int(len(c) * 0.7):]))):
        py = logic.backtest(None, h_, l_, c_)
        jt = res[p][name]
        if len(py) != len(jt) or any(a["dir"] != b["dir"] or abs(a["ret"] - b["ret"]) > 1e-9 or a["win"] != b["win"]
                                     for a, b in zip(py, jt)):
            bad += 1
            print("trade diff", p, name, len(py), len(jt))
        else:
            print(p, name, "取引", len(py), "件 一致")
    for k, t in enumerate(range(len(c) - 60, len(c))):
        if logic.signal_day(sc, t) != res[p]["days"][k]:
            bad += 1
            print("signalDay diff", p, t, logic.signal_day(sc, t), res[p]["days"][k])
print("食い違い", bad)
sys.exit(1 if bad else 0)
