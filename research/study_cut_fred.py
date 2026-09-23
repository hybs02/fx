# -*- coding: utf-8 -*-
"""T1 の続き：3つ目の判定時刻＝NY 正午（日本の深夜1〜2時）。FRB（FRED H.10）の公表レートで22年。
朝9時（Yahoo）・14:15 CET（ECB）と同じ「終値だけの近似」で比べる。クロス円は米ドル建てから合成。"""
import sys, io, csv, datetime as dt, os
from common import PAIRS, SPREAD, pip, HERE
from study_cut import close_only, summ, pf

sys.stdout.reconfigure(encoding="utf-8")


def load(s):
    d = {}
    for r in csv.DictReader(io.open(os.path.join(HERE, "cache", f"fred_{s}.csv"), encoding="utf-8")):
        v = r[s]
        if v and v != "." and r["observation_date"] >= "2003-06-01":
            d[r["observation_date"]] = float(v)
    return d


JPY, EUR, GBP, AUD, CAD, CHF, NZD = (load(s) for s in ("DEXJPUS", "DEXUSEU", "DEXUSUK", "DEXUSAL", "DEXCAUS", "DEXSZUS", "DEXUSNZ"))
# 1 基準通貨 = ? 米ドル
USDper = {"EUR": EUR, "GBP": GBP, "AUD": AUD, "NZD": NZD,
          "CAD": {k: 1 / v for k, v in CAD.items()}, "CHF": {k: 1 / v for k, v in CHF.items()}, "USD": None}


def series(p):
    b, q = p[:3], p[3:]
    days = sorted(JPY)
    out = []
    for d in days:
        try:
            ub = 1.0 if b == "USD" else USDper[b][d]           # 基準通貨→米ドル
            if q == "JPY":
                v = ub * JPY[d]
            elif q == "USD":
                v = ub
            else:
                v = ub / USDper[q][d]
        except KeyError:
            continue
        out.append((d, v))
    return out


allr, eras = [], {}
for p in PAIRS:
    s = series(p)
    D, C = [x[0] for x in s], [x[1] for x in s]
    for i, r in close_only(C, SPREAD[p] * pip(p)):
        allr.append(r)
        y = int(D[i][:4])
        k = "2004-10" if y < 2011 else "2011-14" if y < 2015 else "2015-18" if y < 2019 else "2019-26"
        eras.setdefault(k, []).append(r)
print(f"  NY正午（FRB）      {summ(allr)}   時代別 " + " / ".join(f"{k} {pf(v):.2f}" for k, v in sorted(eras.items())))
