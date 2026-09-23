# -*- coding: utf-8 -*-
"""logic.py の時刻に縛られない版が、study_cut.py の rolling(delay=0) と同じ取引を出すかの確認"""
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
print("一致" if sorted(round(x, 9) for x in allr) == sorted(round(x, 9) for x in ref) else "食い違い")
