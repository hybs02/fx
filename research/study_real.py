# -*- coding: utf-8 -*-
"""現実の取引で効くのに、今までの検証に入っていなかったもの（1時間ごとに判定する形・2024年7月〜）。

 R1 入るのが大きく遅れたら（GitHub の定時実行は中央値2時間・最大7.7時間遅れ、3分の1は起動しない）
 R2 スワップ：1週間持つので毎日つく。DMM の現在値（2026-09-23・1万通貨1日あたりの円）で概算
 R3 早朝 5〜9 時（日本）はスプレッドが原則固定の外で大きく広がる（例 USD/JPY 0.2→3.9銭）
 R4 1時間足の異常値（1時間で値幅が大きすぎる足）
"""
import sys, statistics, datetime as dt
from common import PAIRS, SPREAD, pip, load_hourly, logic
import study_cut as S

sys.stdout.reconfigure(encoding="utf-8")
# DMM スワップ（買い, 売り）円/日/1万通貨。2026-09-23 公式スワップカレンダー（受取日 9/24 の 3日分÷3）
SWAP = {"USDJPY": (115, -118), "EURJPY": (73, -76), "GBPJPY": (146, -149), "AUDJPY": (90, -93),
        "NZDJPY": (35, -38), "CADJPY": (30, -33), "CHFJPY": (-33, 30), "EURUSD": (-73, 70),
        "GBPUSD": (-15, 12), "AUDUSD": (4, -7), "EURGBP": (-57, 54)}


def pf(r):
    g = sum(x for x in r if x > 0); l = -sum(x for x in r if x < 0)
    return g / l if l > 0 else float("nan")


def main():
    H = {p: load_hourly(p) for p in PAIRS}
    phases = {p: logic.phase_series(H[p]["t"], H[p]["h"], H[p]["l"], H[p]["c"]) for p in PAIRS}

    print("== R1 遅れて入る（アプリと同じ logic.rolling_backtest：DMM の取引時間だけ・出口は入った1週間後）==")
    states = {p: (lambda st: (st, logic.rolling_events(st)))(logic.rolling_state(phases[p])) for p in PAIRS}
    for d in (0, 1, 2, 3, 4, 6, 8, 12, 24):
        r = []
        for p in PAIRS:
            st, ev = states[p]
            r += [x["ret"] for x in logic.rolling_backtest(H[p], phases[p], st, ev, cost=SPREAD[p] * pip(p), delay=d)]
        print(f"   {d:2d}時間後  n={len(r)} 平均{statistics.mean(r):+.3f}% PF{pf(r):.2f}")

    # 取引の一覧（時刻つき）
    usdjpy = H["USDJPY"]["c"][-1]; gbpjpy = H["GBPJPY"]["c"][-1]
    trades = []
    for p in PAIRS:
        h = H[p]; ph = phases[p]
        st = logic.rolling_state(ph); ev = logic.rolling_events(st)
        for x in logic.rolling_backtest(h, ph, st, ev, cost=SPREAD[p] * pip(p)):
            x["pair"] = p
            trades.append(x)
    base = [x["ret"] for x in trades]
    print(f"\n   基準（スプレッドのみ） n={len(base)} 平均{statistics.mean(base):+.3f}% PF{pf(base):.2f}")

    print("\n== R2 スワップ込み（いまの DMM の値で、持った日数ぶん）==")
    sw = []
    for x in trades:
        p = x["pair"]
        yen_price = x["entry"] * (1 if p.endswith("JPY") else (usdjpy if p.endswith("USD") else gbpjpy))
        per_day = SWAP[p][0 if x["dir"] == 1 else 1] / (10000 * yen_price) * 100      # 価格に対する % / 日
        days = (x["tx"] - x["t"]) / 86400
        x["swap"] = per_day * days
        sw.append(x["ret"] + x["swap"])
    print(f"   スワップ込み n={len(sw)} 平均{statistics.mean(sw):+.3f}% PF{pf(sw):.2f}")
    for d, nm in ((1, "買い"), (-1, "売り")):
        a = [x["ret"] for x in trades if x["dir"] == d]; b = [x["ret"] + x["swap"] for x in trades if x["dir"] == d]
        s = [x["swap"] for x in trades if x["dir"] == d]
        print(f"   {nm}: 前 平均{statistics.mean(a):+.3f}% PF{pf(a):.2f} → 後 平均{statistics.mean(b):+.3f}% PF{pf(b):.2f}（スワップ 平均{statistics.mean(s):+.3f}%）")

    print("\n== R3 早朝（日本 5〜9 時）に入る・出る取引 ==")
    jh = lambda t: (t // 3600 + 9) % 24
    early = [x for x in trades if 5 <= jh(x["t"]) < 9 or 5 <= jh(x["tx"]) < 9]
    print(f"   入るか出るかが早朝の取引 {len(early)}/{len(trades)}")
    # 早朝はスプレッドが原則の10倍と仮定した時
    worse = []
    for x in trades:
        extra = 0.0
        for tt in (x["t"], x["tx"]):
            if 5 <= jh(tt) < 9:
                extra += SPREAD[x["pair"]] * pip(x["pair"]) * 9 / 2        # 片道ぶんの上乗せ（10倍−1倍）
        worse.append(x["ret"] - extra / x["entry"] * 100)
    print(f"   早朝はスプレッド10倍とした時 平均{statistics.mean(worse):+.3f}% PF{pf(worse):.2f}")
    # 早朝のサインは 9 時まで待って入る／出るのも 9 時まで待つ場合
    alt = []
    for x in trades:
        h = H[x["pair"]]; end = {t + 3600: i for i, t in enumerate(h["t"])}
        t0, t1 = x["t"], x["tx"]
        while 5 <= jh(t0) < 9: t0 += 3600
        while 5 <= jh(t1) < 9: t1 += 3600
        if t0 not in end or t1 not in end or x["how"] == "sl":
            alt.append(x["ret"]); continue
        e, ex = h["c"][end[t0]], h["c"][end[t1]]
        alt.append(((ex - e) * x["dir"] - SPREAD[x["pair"]] * pip(x["pair"])) / e * 100)
    print(f"   早朝のサインは9時まで待って入り、手仕舞いも9時まで待つ 平均{statistics.mean(alt):+.3f}% PF{pf(alt):.2f}")

    print("\n== R4 1時間足の異常値（1時間の値幅が ATR の2倍超／前の終値から2%超の飛び）==")
    for p in PAIRS:
        h = H[p]
        rng = [(hh - ll) / c * 100 for hh, ll, c in zip(h["h"], h["l"], h["c"])]
        med = statistics.median(rng)
        big = [(dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d %H:%M"), round(r, 2))
               for t, r in zip(h["t"], rng) if r > med * 15]
        jump = sum(1 for i in range(1, len(h["c"])) if abs(h["o"][i] / h["c"][i - 1] - 1) > 0.02)
        print(f"   {p}: 1時間の値幅の中央値 {med:.3f}%  15倍超 {len(big)}本 {big[:3]}  前の足から2%超の飛び {jump}本")


if __name__ == "__main__":
    main()
