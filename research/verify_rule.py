# -*- coding: utf-8 -*-
"""logic.py（アプリ本体）の規則が、検証スクリプト study_rsi.sim と同じ取引を出すかの確認と、
アプリに載せる成績の最終値（DMM 公式スプレッド込み）。"""
import sys, datetime as dt, statistics
from common import PAIRS, SPREAD, pip, load_bars, logic
import study_rsi as S

sys.stdout.reconfigure(encoding="utf-8")
ERAS = [("2004-10", dt.date(2004, 1, 1), dt.date(2011, 1, 1)), ("2011-14", dt.date(2011, 1, 1), dt.date(2015, 1, 1)),
        ("2015-18", dt.date(2015, 1, 1), dt.date(2019, 1, 1)), ("2019-21", dt.date(2019, 1, 1), dt.date(2021, 9, 1)),
        ("直近5年", dt.date(2021, 9, 1), dt.date(2027, 1, 1)), ("直近1年", dt.date(2025, 9, 1), dt.date(2027, 1, 1))]
allt, bad = [], 0
for p in PAIRS:
    b = load_bars(p)
    sig, _ = logic.signals(b["C"])
    tr = logic.backtest(b, sig, cost=SPREAD[p] * pip(p))
    for t in tr:
        t["date"] = b["date"][t["i"]]; t["pair"] = p
    allt += tr
    # 検証スクリプトの計算と照合
    b["atr"] = [logic.atr_at(b["H"], b["L"], b["C"], i) for i in range(len(b["C"]))]
    b["rsi"] = {14: logic.rsi_series(b["C"], 14)}; b["ma200"] = logic.sma_series(b["C"], 200)
    ref = [x for x in S.sim(b, S.signals(b, 25, "none", True, 14), 3, None, 5, p) if x["i"] + 5 < len(b["C"])]
    if [(x["i"], round(x["ret"], 9)) for x in ref] != [(x["i"], round(x["ret"], 9)) for x in tr]:
        bad += 1; print("食い違い", p, len(ref), len(tr))
print("検証スクリプトとの食い違い", bad)
s = logic.stats(allt); print("全期間", s)
for nm, a, z in ERAS:
    print(" ", nm, logic.stats([t for t in allt if a <= t["date"] < z]))
print(" 買い", logic.stats([t for t in allt if t["dir"] == 1]))
print(" 売り", logic.stats([t for t in allt if t["dir"] == -1]))
