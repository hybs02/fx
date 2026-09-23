# -*- coding: utf-8 -*-
"""M4 入るのが遅れたら成績はどうなるか（1時間足・直近 2 年）。

サインは毎朝 9 時（UTC 0 時）の値で決まる。実際には
  ・自動更新（GitHub Actions）が走るまで数分〜1時間
  ・本人がアプリを開いて DMM で注文するまで
の遅れがある。h 時間遅れて入り、同じく 5 日後の同じ時刻に手仕舞う場合を 1 時間足で再現する。
損切りは実際に入った値から ATR×SL（アプリの「約定レートで計算」と同じ）。
"""
import sys, datetime as dt, statistics
from common import PAIRS, SPREAD, pip, load_bars, load_hourly, logic

sys.stdout.reconfigure(encoding="utf-8")
RSI_LO, SL, HOLD = 25, 3.0, 5


def pf(r):
    g = sum(x for x in r if x > 0); l = -sum(x for x in r if x < 0)
    return g / l if l > 0 else 9.99


def main():
    res = {h: [] for h in (0, 1, 2, 3, 6, 9, 12)}
    daily_sim = []
    for p in PAIRS:
        b = load_bars(p)
        C = b["C"]
        r = logic.rsi_series(C)
        atr = [logic.atr_at(b["H"], b["L"], C, i) for i in range(len(C))]
        hr = load_hourly(p)
        # 1時間足： 時刻 → (高値, 安値, 終値)。キーは「足の終わりの時刻」
        hend = {t + 3600: (h_, l_, c_) for t, h_, l_, c_ in zip(hr["t"], hr["h"], hr["l"], hr["c"])}
        ends = sorted(hend)
        first = dt.date.fromtimestamp(ends[0]) + dt.timedelta(days=3)
        cost = SPREAD[p] * pip(p)
        nf = 0
        for i in range(250, len(C) - HOLD - 1):
            if b["date"][i] < first or i < nf:
                continue
            if r[i] is None or r[i - 1] is None:
                continue
            d = 1 if (r[i] <= RSI_LO < r[i - 1]) else (-1 if (r[i] >= 100 - RSI_LO > r[i - 1]) else 0)
            if not d:
                continue
            nf = i + HOLD + 1
            t0 = int(dt.datetime(b["date"][i].year, b["date"][i].month, b["date"][i].day,
                                 tzinfo=dt.timezone.utc).timestamp())            # その日の UTC 0 時
            tx = int(dt.datetime(b["date"][i + HOLD].year, b["date"][i + HOLD].month, b["date"][i + HOLD].day,
                                 tzinfo=dt.timezone.utc).timestamp())            # 5 本後の UTC 0 時
            # 日足で同じ取引を計算（比較用）
            e0 = C[i]; s0 = e0 - d * SL * atr[i]; out = None
            for j in range(i + 1, i + 1 + HOLD):
                if (b["L"][j] <= s0) if d == 1 else (b["H"][j] >= s0):
                    out = s0; break
            out = C[i + HOLD] if out is None else out
            daily_sim.append(((out - e0) * d - cost) / e0 * 100)
            for h in res:
                te, tq = t0 + h * 3600, tx + h * 3600
                if te not in hend or tq not in hend:
                    # その時刻の足が無い（週末をまたぐ等）→ 直後の足を使う
                    k = next((x for x in ends if x >= te), None)
                    q = next((x for x in ends if x >= tq), None)
                    if k is None or q is None:
                        continue
                    te, tq = k, q
                e = hend[te][2]
                s = e - d * SL * atr[i]
                ex = None
                for t in ends:
                    if t <= te or t > tq:
                        continue
                    hh, ll, cc = hend[t]
                    if (ll <= s) if d == 1 else (hh >= s):
                        ex = s; break
                ex = hend[tq][2] if ex is None else ex
                res[h].append(((ex - e) * d - cost) / e * 100)
    print(f"直近2年の取引 {len(daily_sim)} 件（RSI14≤{RSI_LO}/≥{100-RSI_LO} 初日・損切りATR×{SL}・{HOLD}日）")
    print(f"  日足で計算           平均{statistics.mean(daily_sim):+.3f}% PF{pf(daily_sim):.2f}")
    base = res[0]
    for h, r in res.items():
        diff = [a - b for a, b in zip(r, base)] if len(r) == len(base) else []
        extra = f"  0時間との差 平均{statistics.mean(diff):+.3f}% (標準誤差 {statistics.stdev(diff)/len(diff)**.5:.3f})" if diff and h else ""
        print(f"  {h:2d}時間後に入る（{9+h}時） n={len(r)} 平均{statistics.mean(r):+.3f}% PF{pf(r):.2f} 勝率{sum(1 for x in r if x>0)/len(r)*100:.0f}%{extra}")


if __name__ == "__main__":
    main()
