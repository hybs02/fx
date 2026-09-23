# -*- coding: utf-8 -*-
"""判定する時刻を「朝9時」に固定しなくてよいか。

 T1 22年：ECB の参照レート（毎日 14:15 CET ＝ 朝9時とは全く別の時刻）で同じ規則を回し、
          朝9時締めと同じ近似（終値だけで ATR と損切りを見る）で比べる。
 T2 2年：1時間足から「毎日 h 時締め」の日足を 24 通り作り、h ごとに同じ規則を回す。
 T3 2年：1時間ごとに『直近24時間ごとの日足』で RSI を計算し、しきい値を越えた最初の時刻に入る
          （＝時刻に縛られない版）。5日後の同じ時刻に出る・損切り ATR×3 は1時間足で判定。
"""
import sys, bisect, statistics, datetime as dt
from common import PAIRS, SPREAD, pip, load_bars, load_ecb, load_hourly, logic

sys.stdout.reconfigure(encoding="utf-8")
LO, HI, SLK, HOLD = 25, 75, 3.0, 5


def pf(r):
    g = sum(x for x in r if x > 0); l = -sum(x for x in r if x < 0)
    return g / l if l > 0 else float("nan")


def summ(r):
    if not r:
        return "取引なし"
    return f"n={len(r):4d} 勝率{sum(1 for x in r if x > 0) / len(r) * 100:4.1f}% 平均{statistics.mean(r):+.3f}% PF{pf(r):.2f}"


def close_only(C, cost, start=250):
    """終値だけで回す（ATR≒終値の変化の平均×2.24、損切りは終値で判定）。T1 の比較用"""
    sig, _ = logic.signals(C)
    out, nf = [], start
    for i in range(start, len(C) - HOLD):
        if i < nf or not sig[i]:
            continue
        d = sig[i]
        a = sum(abs(C[k] - C[k - 1]) for k in range(i - 13, i + 1)) / 14 * 2.24
        stop = C[i] - d * SLK * a
        ex, j = C[i + HOLD], i + HOLD
        for k in range(i + 1, i + HOLD + 1):
            if (C[k] <= stop) if d == 1 else (C[k] >= stop):
                ex, j = C[k], k; break
        out.append((i, ((ex - C[i]) * d - cost) / C[i] * 100))
        nf = j + 1
    return out


def main():
    print("== T1 22年：判定の時刻が違う2本（終値だけの同じ近似で比較）==")
    for name in ("朝9時締め（Yahoo）", "14:15 CET（ECB）"):
        allr, eras = [], {}
        for p in PAIRS:
            if name.startswith("朝"):
                b = load_bars(p); C, D = b["C"], b["date"]
            else:
                e = load_ecb(p); D = sorted(e); C = [e[x] for x in D]
            for i, r in close_only(C, SPREAD[p] * pip(p)):
                allr.append(r)
                y = D[i].year
                k = "2004-10" if y < 2011 else "2011-14" if y < 2015 else "2015-18" if y < 2019 else "2019-26"
                eras.setdefault(k, []).append(r)
        print(f"  {name:14s} {summ(allr)}   時代別 " + " / ".join(f"{k} {pf(v):.2f}" for k, v in sorted(eras.items())))

    print("\n== T2 2年：何時締めの日足でも同じか（1時間足・24通り）==")
    H = {p: load_hourly(p) for p in PAIRS}
    by_h, phases = {}, {}
    for p in PAIRS:
        h = H[p]
        T = h["t"]
        # 時刻 → その時刻「まで」の1時間足（[T-1h, T) の足）の番号
        end = {t + 3600: i for i, t in enumerate(T)}
        ph = {}
        for hh in range(24):
            ts = sorted(t for t in end if (t // 3600) % 24 == hh)
            C, Hh, Ll, prev = [], [], [], None
            for t in ts:
                i = end[t]
                if prev is None:
                    lo_i = i
                else:
                    lo_i = end[prev] + 1
                seg = range(lo_i, i + 1)
                C.append(h["c"][i]); Hh.append(max(h["h"][k] for k in seg)); Ll.append(min(h["l"][k] for k in seg))
                prev = t
            ph[hh] = {"t": ts, "C": C, "H": Hh, "L": Ll}
            sig, _ = logic.signals(C)
            tr = logic.backtest(ph[hh], sig, cost=SPREAD[p] * pip(p), start=150)
            by_h.setdefault(hh, []).extend(t["ret"] for t in tr)
        phases[p] = ph
    rows = []
    for hh in range(24):
        r = by_h[hh]
        rows.append(pf(r))
        print(f"  UTC {hh:2d}時締め（日本 {(hh + 9) % 24:2d}時）{summ(r)}")
    print(f"  24通りの PF：中央値 {statistics.median(rows):.2f}・最小 {min(rows):.2f}・最大 {max(rows):.2f}")

    print("\n== T3 2年：時刻に縛られない版（1時間ごとに直近の日足で判定）==")
    for delay in (0, 1, 2, 3, 4, 6):
        print(f"   {delay}時間後に入る  {summ(rolling(H, phases, delay))}")
    print("   比較：朝9時締め（T2 の UTC 0 時）", summ(by_h[0]))


def rolling(H, phases, delay=0):
    """しきい値を越えた時刻 b から delay 時間後に入り、b の 5 取引日後（＋delay）に出る"""
    res = []
    for p in PAIRS:
        h, ph = H[p], phases[p]
        T = h["t"]
        end = {t + 3600: i for i, t in enumerate(T)}
        # 各時刻の RSI と ATR（その時刻締めの日足で）
        rs, at = {}, {}
        for hh, s in ph.items():
            r = logic.rsi_series(s["C"])
            for k, t in enumerate(s["t"]):
                if k >= 150:
                    rs[t] = r[k]
                    at[t] = logic.atr_at(s["H"], s["L"], s["C"], k)
        times = sorted(rs)
        busy_until, last_cross = 0, {1: -1e18, -1: -1e18}
        for a, b in zip(times, times[1:]):
            if b - a > 3 * 3600:          # 週末をまたぐ
                continue
            ra, rb = rs[a], rs[b]
            d = 1 if rb <= LO < ra else (-1 if rb >= HI > ra else 0)
            if not d:
                continue
            # 同じ向きの越えが 5 日以内にあったら同じ山とみなす（検証では持っている間なので入らない）
            fresh = b - last_cross[d] > 5 * 86400
            last_cross[d] = b
            if not fresh or b < busy_until:
                continue
            # 5 取引日後の同じ時刻
            s = ph[(b // 3600) % 24]
            k0 = s["t"].index(b)
            if k0 + HOLD >= len(s["t"]):
                continue
            te, tx = b + delay * 3600, s["t"][k0 + HOLD] + delay * 3600
            if te not in end or tx not in end:
                continue
            e = h["c"][end[te]]
            stop = e - d * SLK * at[b]
            ex = h["c"][end[tx]]
            for t in range(te + 3600, tx + 1, 3600):
                i = end.get(t)
                if i is None:
                    continue
                if (h["l"][i] <= stop) if d == 1 else (h["h"][i] >= stop):
                    ex = stop; tx = t; break
            res.append(((ex - e) * d - SPREAD[p] * pip(p)) / e * 100)
            busy_until = tx
    return res


if __name__ == "__main__":
    main()
