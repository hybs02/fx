# -*- coding: utf-8 -*-
"""logic.py の時刻に縛られない版と、最初の検証（study_cut.py の rolling）の比べ。
2026-09-23 夜、アプリ側（logic.rolling_backtest）に2つ足したので、一致はしない：
  ・DMM の取引時間外（土曜 5:50〜月曜 7:00）のサインは入らない（Yahoo には閉まった後の足もある）
  ・出口は「入った時刻の1週間後」（取引時間外なら、その前で最後に取引できる時刻）
study_cut は最初の定義（89回・PF1.95）のまま残し、アプリの数字は logic 側（86回・PF1.92）を正とする。"""
import sys
from common import PAIRS, SPREAD, pip, load_hourly, logic
import study_cut as S

sys.stdout.reconfigure(encoding="utf-8")
H = {p: load_hourly(p) for p in PAIRS}
allr = []
phases = {}
for p in PAIRS:
    h = H[p]
    ph = logic.phase_series(h["t"], h["h"], h["l"], h["c"])
    phases[p] = ph
    st = logic.rolling_state(ph)
    ev = logic.rolling_events(st)
    allr += [x["ret"] for x in logic.rolling_backtest(h, ph, st, ev, cost=SPREAD[p] * pip(p))]
ref = S.rolling(H, phases, 0)
print("logic:", S.summ(allr))
print("study:", S.summ(ref))
print("（差は取引時間外のサインを除いた分と、出口の定義の違い）")
