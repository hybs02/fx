# -*- coding: utf-8 -*-
"""ドル円だけで規則を選ぶ（朝9時締めの日足・スプレッドとスワップ込み）。

手順（のぞき見を防ぐ）:
  設計期間 2004〜2018 だけで選ぶ → 選ぶのに使っていない 2019〜 で確かめる。
  選ぶ基準は「設計期間の 3 つの時代それぞれの PF の最小値」。ドル円1ペアは取引が少ないので、
  設計期間の取引が 40 回に満たない設定は選ばない。
"""
import sys, datetime as dt
from common import load_bars, load_hourly, load_irx, SPREAD, pip, logic

sys.stdout.reconfigure(encoding="utf-8")
P = "USDJPY"
COST = SPREAD[P] * pip(P)
ERAS = [("2004-10", "2004", "2011"), ("2011-14", "2011", "2015"), ("2015-18", "2015", "2019"),
        ("2019-21", "2019", "2021-09"), ("2021-", "2021-09", "2100")]
SPLIT = "2019"
b = load_bars(P)
D = [x.isoformat() for x in b["date"]]
irx = load_irx()


def ts(i):
    return dt.datetime.combine(b["date"][i], dt.time(), dt.timezone.utc).timestamp()


def run(lo, hi, sl, hold):
    s, _ = logic.signals(b["C"], lo, hi)
    tr = logic.backtest(b, s, sl_atr=sl, hold=hold, cost=COST)
    for t in tr:
        t["ret"] += logic.swap_pct(irx, ts(t["i"]), ts(t["j"]), t["dir"])
    return tr


def pf(tr):
    g = sum(t["ret"] for t in tr if t["ret"] > 0); l = -sum(t["ret"] for t in tr if t["ret"] < 0)
    return g / l if l > 0 else 9.99


def era(tr, a, z):
    return [t for t in tr if a <= D[t["i"]] < z]


def line(name, tr):
    s = logic.stats(tr)
    if not s:
        return print(f"{name:30s} 取引なし")
    e = " ".join(f"{pf(era(tr, a, z)):5.2f}({len(era(tr, a, z)):2d})" for _, a, z in ERAS)
    print(f"{name:30s} n={s['n']:3d} 勝率{s['wr']:5.1f}% 平均{s['exp']:+.3f}% PF{pf(tr):4.2f} | {e}")


print("時代:", " ".join(e[0] for e in ERAS), "  （かっこ内は回数）")
print("\n== 11 ペアで決めた規則をドル円だけに当てる ==")
old = run(25, 75, 3.0, 5)
line("RSI25/75 ATR×3 1週間", old)
line("  買いだけ", [t for t in old if t["dir"] == 1])
line("  売りだけ", [t for t in old if t["dir"] == -1])

print("\n== 設計期間（2004〜2018）だけで選ぶ ==")
rows = []
for lo in (20, 25, 30, 35):
    for sl in (2.0, 3.0, 4.0):
        for hold in (3, 5, 7, 10):
            tr = run(lo, 100 - lo, sl, hold)
            dsg = [t for t in tr if D[t["i"]] < SPLIT]
            tst = [t for t in tr if D[t["i"]] >= SPLIT]
            worst = min(pf(era(tr, a, z)) for _, a, z in ERAS[:3])
            rows.append({"lo": lo, "sl": sl, "hold": hold, "worst": worst, "nd": len(dsg), "pfd": pf(dsg),
                         "nt": len(tst), "pft": pf(tst)})
ok = sorted([r for r in rows if r["nd"] >= 40], key=lambda r: -r["worst"])
print("順位  設定                 設計の最悪時代PF  設計PF(回)    確かめPF(回)")
for k, r in enumerate(ok[:12], 1):
    print(f"{k:3d}  RSI{r['lo']}/{100-r['lo']} ATR×{r['sl']:.0f} {r['hold']:2d}日   {r['worst']:5.2f}"
          f"          {r['pfd']:4.2f}({r['nd']:3d})   {r['pft']:4.2f}({r['nt']:2d})")
print("\nRSI 30/70 の周辺（確かめ期間の PF）:")
for sl in (2.0, 3.0, 4.0):
    print(f"  ATR×{sl:.0f}: " + "  ".join(f"{r['hold']}日 {r['pft']:.2f}" for r in rows if r["lo"] == 30 and r["sl"] == sl))
print("確かめ期間で負け越した設定（RSI30/70）:",
      [f"ATR×{r['sl']:.0f}/{r['hold']}日" for r in rows if r["lo"] == 30 and r["pft"] < 1] or "なし")

best = ok[0]
pick = run(best["lo"], 100 - best["lo"], best["sl"], best["hold"])
print(f"\n== 選んだ規則 RSI{best['lo']}/{100-best['lo']} ATR×{best['sl']:.0f} {best['hold']}日 ==")
line("全体", pick)
line("  買いだけ", [t for t in pick if t["dir"] == 1])
line("  売りだけ", [t for t in pick if t["dir"] == -1])
sw = [logic.swap_pct(irx, ts(t["i"]), ts(t["j"]), t["dir"]) for t in pick]
print(f"  スワップの寄与 1回平均 {sum(sw)/len(sw):+.3f}%（買い {sum(x for x, t in zip(sw, pick) if t['dir']==1)/max(1,sum(1 for t in pick if t['dir']==1)):+.3f}%・"
      f"売り {sum(x for x, t in zip(sw, pick) if t['dir']==-1)/max(1,sum(1 for t in pick if t['dir']==-1)):+.3f}%）")

print("\n== 1時間ごとの判定（直近約2年・DMM の取引時間だけ・1週間後に出る・スワップ込み） ==")
h = load_hourly(P)
ph = logic.phase_series(h["t"], h["h"], h["l"], h["c"])
st = logic.rolling_state(ph)
for lo, sl in ((25, 3.0), (best["lo"], 3.0), (best["lo"], best["sl"])):
    ev = logic.rolling_events(st, lo, 100 - lo)
    for delay in (0, 2, 3, 6, 8, 12, 24):
        rb = logic.rolling_backtest(h, ph, st, ev, cost=COST, sl_atr=sl, delay=delay)
        for t in rb:
            t["ret"] += logic.swap_pct(irx, t["te"], t["tx"], t["dir"])
        s = logic.stats(rb)
        if s:
            print(f"  RSI{lo}/{100-lo} ATR×{sl:.0f} 遅れ{delay:2d}h: n={s['n']:2d} 勝率{s['wr']:5.1f}% 平均{s['exp']:+.3f}% PF{pf(rb):5.2f}"
                  f"（買い{sum(1 for t in rb if t['dir'] == 1)}・売り{sum(1 for t in rb if t['dir'] == -1)}）")
