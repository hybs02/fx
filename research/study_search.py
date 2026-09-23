# -*- coding: utf-8 -*-
"""どの時代でも崩れない規則を探す（組み直した日足・スプレッド込み・11ペア合算）。

手順（のぞき見を防ぐ）:
  設計期間 2004〜2018 だけで規則を選ぶ → 選ぶのに使っていない 2019〜2026 で確かめる。
  選ぶ基準は「設計期間の 3 つの時代それぞれの PF の最小値」（どこかで大負けする規則は落ちる）。

型:
  F1 いまの採点（RSI±3・BB±2・MA±1・MACD±1）
  F2 RSI(14) の行きすぎ＋200日線の向き（上昇中の押し目だけ買う／下降中の戻りだけ売る 等）
  F3 RSI(2) の短期の行きすぎ＋200日線（Connors 型）
  F4 高値・安値ブレイク（ドンチャン）＝順張り
  F5 時系列モメンタム（N 日前より上なら買い・下なら売り。向きが変わった日に入る）
出口はすべて「OCO（ATR 倍の利確・損切り）＋ 期限で手仕舞い」＝DMM アプリで実行できる形だけ。
"""
import sys, datetime as dt, itertools, json, os
from common import PAIRS, SPREAD, pip, load_bars, legacy_logic as logic, HERE

sys.stdout.reconfigure(encoding="utf-8")

DESIGN = [(dt.date(2004, 1, 1), dt.date(2011, 1, 1)), (dt.date(2011, 1, 1), dt.date(2015, 1, 1)),
          (dt.date(2015, 1, 1), dt.date(2019, 1, 1))]
TEST = [(dt.date(2019, 1, 1), dt.date(2021, 9, 1)), (dt.date(2021, 9, 1), dt.date(2027, 1, 1))]


def rsi_n(c, n):
    return logic.rsi_series(c, n)


def sim(b, sig, sl, tp, hold, pair):
    """sig[i] ∈ {-1,0,1}（i 日 9 時に入る向き）。1 ペア 1 ポジション。"""
    H, L, C, dates = b["H"], b["L"], b["C"], b["date"]
    n = len(C)
    out, nf = [], 250
    cost = SPREAD[pair] * pip(pair)
    for i in range(250, n - 1):
        if i < nf or not sig[i]:
            continue
        d = sig[i]
        a = b["atr"][i]
        if not a:
            continue
        e = C[i]
        s, t = e - d * sl * a, e + d * tp * a
        res, j = None, i + 1
        for j in range(i + 1, min(i + 1 + hold, n)):
            if (L[j] <= s) if d == 1 else (H[j] >= s):
                res = s; break
            if (H[j] >= t) if d == 1 else (L[j] <= t):
                res = t; break
        if res is None:
            res = C[j]
        out.append((dates[i], ((res - e) * d - cost) / e * 100))
        nf = j + 1
    return out


def pf(rets):
    g = sum(r for r in rets if r > 0); l = -sum(r for r in rets if r < 0)
    return g / l if l > 0 else (9.99 if g > 0 else 0.0)


def evaluate(trades):
    per = []
    for a, b in DESIGN + TEST:
        r = [x[1] for x in trades if a <= x[0] < b]
        per.append((pf(r), len(r), sum(r)))
    return per


def main():
    B = {}
    for p in PAIRS:
        b = load_bars(p)
        C = b["C"]
        b["atr"] = [logic.atr_at(b["H"], b["L"], C, i) for i in range(len(C))]
        b["sc"] = logic.score_series(C)
        b["r14"] = rsi_n(C, 14)
        b["r2"] = rsi_n(C, 2)
        b["ma200"] = logic.sma_series(C, 200)
        B[p] = b

    def f1(b, gate, fresh):
        sc, s = b["sc"], [0] * len(b["C"])
        for i in range(1, len(s)):
            d = logic.direction(sc[i], gate)
            if d and not (fresh and logic.direction(sc[i - 1], gate) == d):
                s[i] = d
        return s

    def f2(b, lo, mode):
        r, m, C, s = b["r14"], b["ma200"], b["C"], [0] * len(b["C"])
        for i in range(1, len(s)):
            if r[i] is None or m[i] is None or r[i - 1] is None:
                continue
            up = C[i] > m[i]
            buy = r[i] <= lo and r[i - 1] > lo          # 初日だけ
            sell = r[i] >= 100 - lo and r[i - 1] < 100 - lo
            if mode == "with":        # 上昇中の押し目買い・下降中の戻り売り
                buy, sell = buy and up, sell and not up
            elif mode == "against":
                buy, sell = buy and not up, sell and up
            s[i] = 1 if buy else (-1 if sell else 0)
        return s

    def f3(b, lo):
        r, m, C, s = b["r2"], b["ma200"], b["C"], [0] * len(b["C"])
        for i in range(1, len(s)):
            if r[i] is None or m[i] is None:
                continue
            up = C[i] > m[i]
            s[i] = 1 if (r[i] <= lo and up) else (-1 if (r[i] >= 100 - lo and not up) else 0)
        return s

    def f4(b, n):
        C, s = b["C"], [0] * len(b["C"])
        for i in range(n + 1, len(s)):
            hi, lo = max(C[i - n:i]), min(C[i - n:i])
            phi, plo = max(C[i - n - 1:i - 1]), min(C[i - n - 1:i - 1])
            if C[i] > hi and not C[i - 1] > phi:
                s[i] = 1
            elif C[i] < lo and not C[i - 1] < plo:
                s[i] = -1
        return s

    def f5(b, n):
        C, s = b["C"], [0] * len(b["C"])
        for i in range(n + 1, len(s)):
            d0 = 1 if C[i] > C[i - n] else -1
            d1 = 1 if C[i - 1] > C[i - 1 - n] else -1
            if d0 != d1:
                s[i] = d0
        return s

    EXITS = [(sl, tp, h) for sl, tp in [(1.5, 1.5), (2, 2), (2.5, 2.5), (3, 3), (2, 3), (3, 2), (2, 4), (3, 6)]
             for h in (5, 10, 15, 30)]
    FAM = []
    for g, fr in itertools.product((3, 4, 5), (True, False)):
        FAM.append((f"F1 採点 gate{g} {'初日' if fr else '毎日'}", lambda b, g=g, fr=fr: f1(b, g, fr)))
    for lo, mode in itertools.product((25, 30, 35), ("with", "against", "none")):
        FAM.append((f"F2 RSI14≤{lo} 200日線{mode}", lambda b, lo=lo, mode=mode: f2(b, lo, mode)))
    for lo in (5, 10, 20):
        FAM.append((f"F3 RSI2≤{lo} 順方向", lambda b, lo=lo: f3(b, lo)))
    for n in (20, 55, 100):
        FAM.append((f"F4 {n}日ブレイク", lambda b, n=n: f4(b, n)))
    for n in (20, 60, 120, 250):
        FAM.append((f"F5 {n}日モメンタム転換", lambda b, n=n: f5(b, n)))

    rows = []
    for name, fn in FAM:
        sigs = {p: fn(B[p]) for p in PAIRS}
        for sl, tp, h in EXITS:
            tr = []
            for p in PAIRS:
                tr += sim(B[p], sigs[p], sl, tp, h, p)
            per = evaluate(tr)
            dmin = min(x[0] for x in per[:3])
            dn = sum(x[1] for x in per[:3])
            rows.append({"name": name, "sl": sl, "tp": tp, "hold": h, "design_min": dmin, "design_n": dn,
                         "per": per, "test_min": min(x[0] for x in per[3:]),
                         "test_pf": pf([x[1] for x in tr if x[0] >= dt.date(2019, 1, 1)]),
                         "design_pf": pf([x[1] for x in tr if x[0] < dt.date(2019, 1, 1)])})
    ok = [r for r in rows if r["design_n"] >= 150]
    ok.sort(key=lambda r: -r["design_min"])
    print(f"組み合わせ {len(rows)} 通り（設計期間の取引 150 回以上: {len(ok)}）\n")
    print("設計期間の『最悪の時代の PF』が高い順 上位 25（→ 右が未使用期間での成績）")
    hdr = "  2004-10  2011-14  2015-18 |  2019-21  直近5年"
    print(f"{'規則':32s} {'SL/TP/期限':12s} {hdr}   設計PF 検証PF")
    for r in ok[:25]:
        cells = " ".join(f"{x[0]:5.2f}({x[1]:3d})" for x in r["per"])
        print(f"{r['name']:32s} {r['sl']}/{r['tp']}/{r['hold']:<3d}    {cells}   {r['design_pf']:.2f}  {r['test_pf']:.2f}")
    # いまの規則の位置
    cur = [r for r in rows if r["name"] == "F1 採点 gate3 初日" and r["sl"] == 2.5 and r["tp"] == 2.5 and r["hold"] == 15][0]
    rank = sorted(ok, key=lambda r: -r["design_min"]).index(cur) + 1 if cur in ok else None
    print("\nいまの規則:", " ".join(f"{x[0]:.2f}({x[1]})" for x in cur["per"]), "設計順位", rank)
    # 型ごとの最良（設計基準）と、その検証成績
    print("\n型ごとに設計期間で一番よかった設定 → 未使用期間")
    best = {}
    for r in ok:
        k = r["name"][:2]
        if k not in best:
            best[k] = r
    for k, r in best.items():
        print(f"  {r['name']:32s} {r['sl']}/{r['tp']}/{r['hold']}  設計最悪{r['design_min']:.2f} 設計PF{r['design_pf']:.2f} → 検証PF{r['test_pf']:.2f} 検証最悪{r['test_min']:.2f}")
    # 設計の上位 20 の検証 PF の分布（上位が検証でも良いなら、選び方に意味がある）
    import statistics
    top = ok[:20]; rest = ok[20:]
    print("\n設計上位20 の検証PF 中央値", round(statistics.median(r["test_pf"] for r in top), 3),
          " / 残り の検証PF 中央値", round(statistics.median(r["test_pf"] for r in rest), 3))
    json.dump(rows, open(os.path.join(HERE, "cache", "search_rows.json"), "w"), default=str)


if __name__ == "__main__":
    main()
