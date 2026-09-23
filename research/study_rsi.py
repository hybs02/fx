# -*- coding: utf-8 -*-
"""study_search で頑健だった「RSI(14) の行きすぎ初日 → 数日で手仕舞い」を掘る。
  1 周辺の設定（しきい値・損切り・利確・期限）が一様に良いか（1 点だけ良いなら偶然）
  2 ペア別・年別
  3 利確・損切り・期限のどれで終わるか
"""
import sys, datetime as dt, statistics, collections
from common import PAIRS, SPREAD, pip, load_bars, logic

sys.stdout.reconfigure(encoding="utf-8")
ERAS = [(dt.date(2004, 1, 1), dt.date(2011, 1, 1)), (dt.date(2011, 1, 1), dt.date(2015, 1, 1)),
        (dt.date(2015, 1, 1), dt.date(2019, 1, 1)), (dt.date(2019, 1, 1), dt.date(2021, 9, 1)),
        (dt.date(2021, 9, 1), dt.date(2027, 1, 1))]


def pf(r):
    g = sum(x for x in r if x > 0); l = -sum(x for x in r if x < 0)
    return g / l if l > 0 else 9.99


def signals(b, lo, mode="none", fresh=True, n=14):
    r = b["rsi"][n]
    m, C = b["ma200"], b["C"]
    s = [0] * len(C)
    for i in range(1, len(C)):
        if r[i] is None or r[i - 1] is None or m[i] is None:
            continue
        buy = r[i] <= lo and (not fresh or r[i - 1] > lo)
        sell = r[i] >= 100 - lo and (not fresh or r[i - 1] < 100 - lo)
        up = C[i] > m[i]
        if mode == "against":
            buy, sell = buy and not up, sell and up
        elif mode == "with":
            buy, sell = buy and up, sell and not up
        s[i] = 1 if buy else (-1 if sell else 0)
    return s


def sim(b, sig, sl, tp, hold, pair, cost=True):
    H, L, C = b["H"], b["L"], b["C"]
    n, out, nf = len(C), [], 250
    c = SPREAD[pair] * pip(pair) if cost else 0.0
    for i in range(250, n - 1):
        if i < nf or not sig[i]:
            continue
        d, a, e = sig[i], b["atr"][i], C[i]
        if not a:
            continue
        s = e - d * sl * a if sl else None
        t = e + d * tp * a if tp else None
        res, how, j = None, "time", i + 1
        for j in range(i + 1, min(i + 1 + hold, n)):
            if s is not None and ((L[j] <= s) if d == 1 else (H[j] >= s)):
                res, how = s, "sl"; break
            if t is not None and ((H[j] >= t) if d == 1 else (L[j] <= t)):
                res, how = t, "tp"; break
        if res is None:
            res = C[j]
        out.append({"date": b["date"][i], "pair": pair, "d": d, "ret": ((res - e) * d - c) / e * 100,
                    "how": how, "days": j - i, "i": i})
        nf = j + 1
    return out


def era_pfs(tr):
    return [pf([x["ret"] for x in tr if a <= x["date"] < b]) for a, b in ERAS]


def main():
    B = {}
    for p in PAIRS:
        b = load_bars(p)
        b["atr"] = [logic.atr_at(b["H"], b["L"], b["C"], i) for i in range(len(b["C"]))]
        b["rsi"] = {n: logic.rsi_series(b["C"], n) for n in (7, 14, 21)}
        b["ma200"] = logic.sma_series(b["C"], 200)
        B[p] = b

    def run(lo, mode, sl, tp, hold, fresh=True, n=14, cost=True, pairs=PAIRS):
        tr = []
        for p in pairs:
            tr += sim(B[p], signals(B[p], lo, mode, fresh, n), sl, tp, hold, p, cost)
        return tr

    print("== 1 周辺の設定：5 つの時代の PF（左3つ＝設計、右2つ＝未使用）と全期間 ==")
    print("   しきい値 型       SL  TP 期限 |  2004-10 2011-14 2015-18 | 2019-21 直近5年 | 全期間PF  回数  最悪")
    for lo in (20, 25, 30):
        for mode in ("none", "against"):
            for sl, tp in ((2, None), (3, None), (4, None), (None, None), (3, 3), (3, 6), (2, 4)):
                for hold in (3, 5, 7, 10):
                    tr = run(lo, mode, sl, tp, hold)
                    e = era_pfs(tr)
                    print(f"   RSI≤{lo} {mode:8s} {str(sl):4s} {str(tp):4s} {hold:3d}  | " +
                          " ".join(f"{x:6.2f}" for x in e[:3]) + " | " + " ".join(f"{x:6.2f}" for x in e[3:]) +
                          f" | {pf([x['ret'] for x in tr]):6.2f} {len(tr):5d} {min(e):5.2f}")
        print()

    print("== RSI の期間・初日限定 ==")
    for n in (7, 14, 21):
        for fresh in (True, False):
            tr = run(25, "none", 3, 6, 5, fresh, n)
            e = era_pfs(tr)
            print(f"   RSI{n} 初日{fresh}: " + " ".join(f"{x:.2f}" for x in e) + f"  全期間 {pf([x['ret'] for x in tr]):.2f} n={len(tr)}")

    CH = dict(lo=25, mode="none", sl=3, tp=6, hold=5)
    tr = run(**CH)
    print("\n== 2 候補（RSI14≤25/≥75 初日・SL3/TP6 ATR・5日）のペア別 ==")
    for p in PAIRS:
        t = [x for x in tr if x["pair"] == p]
        e = era_pfs(t)
        wr = sum(1 for x in t if x["ret"] > 0) / len(t) * 100
        print(f"   {p} n={len(t):3d} 勝率{wr:4.1f}% 期待値{statistics.mean(x['ret'] for x in t):+.3f}% PF{pf([x['ret'] for x in t]):.2f}  時代別 " +
              " ".join(f"{x:.2f}" for x in e))
    print("   買い", f"PF{pf([x['ret'] for x in tr if x['d']==1]):.2f} n={sum(1 for x in tr if x['d']==1)}",
          " 売り", f"PF{pf([x['ret'] for x in tr if x['d']==-1]):.2f} n={sum(1 for x in tr if x['d']==-1)}")
    print("\n   年別（合算・%はポジション1つを資金全部で持った時の単純合計ではなく、1取引の平均）")
    by = collections.defaultdict(list)
    for x in tr:
        by[x["date"].year].append(x["ret"])
    neg = 0
    for y in sorted(by):
        r = by[y]
        neg += sum(r) < 0
        print(f"   {y} n={len(r):3d} 合計{sum(r):+6.2f}% PF{pf(r):5.2f}")
    print(f"   負けた年 {neg}/{len(by)}")
    print("\n== 3 終わり方 ==")
    c = collections.Counter(x["how"] for x in tr)
    print("  ", dict(c), " 保有日数", collections.Counter(x["days"] for x in tr))
    for how in ("tp", "sl", "time"):
        r = [x["ret"] for x in tr if x["how"] == how]
        if r:
            print(f"   {how}: n={len(r)} 平均{statistics.mean(r):+.3f}%")
    print("\n   コスト無し全期間 PF", round(pf([x["ret"] for x in run(**CH, cost=False)]), 3))
    wr = sum(1 for x in tr if x["ret"] > 0) / len(tr) * 100
    print(f"   全期間 n={len(tr)} 勝率{wr:.1f}% 期待値{statistics.mean(x['ret'] for x in tr):+.3f}% PF{pf([x['ret'] for x in tr]):.2f}")


if __name__ == "__main__":
    main()
