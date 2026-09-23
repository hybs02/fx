# -*- coding: utf-8 -*-
"""いまの規則（2026-09-08 版）を、組み直した日足（東京 9 時締め・common.load_bars）で 22 年分測り直す。
 M1 時代別（これまでの検証は直近 5 年だけ。2004〜2020 は一度も使っていない＝本当の検証期間）
 M2 保有期限：検証は 15 日で手仕舞うが、アプリの手順は OCO「無期限」で放置 → 現実はどっち？
 M3 キー無し版が使っていた ECB の参照レートで出したサインは、Yahoo のサインと同じ成績か
 M5 スプレッドを引いた後の成績
 比較のため、組み直す前の日足（旧検証と同じ扱い）の数字も並べる。
"""
import sys, datetime as dt, statistics, collections, bisect
from common import PAIRS, SPREAD, pip, load_daily, load_bars, load_ecb, summary, legacy_logic as logic

sys.stdout.reconfigure(encoding="utf-8")

ERAS = [("2004-10", dt.date(2004, 1, 1), dt.date(2011, 1, 1)),
        ("2011-14", dt.date(2011, 1, 1), dt.date(2015, 1, 1)),
        ("2015-18", dt.date(2015, 1, 1), dt.date(2019, 1, 1)),
        ("2019-21", dt.date(2019, 1, 1), dt.date(2021, 9, 1)),
        ("直近5年", dt.date(2021, 9, 1), dt.date(2027, 1, 1)),
        ("直近1年", dt.date(2025, 9, 1), dt.date(2027, 1, 1))]


def load_all(raw=False):
    D = {}
    for p in PAIRS:
        if raw:
            d = load_daily(p)
            b = {"date": d["date"], "C": d["c"], "H": d["h"], "L": d["l"], "snap": [True] * len(d["c"])}
        else:
            b = load_bars(p)
        b["sc"] = logic.score_series(b["C"])
        D[p] = b
    return D


def run(D, max_hold=15, cost=True, key="sc", **kw):
    allt = []
    for p in PAIRS:
        b = D[p]
        ts = logic.backtest(None, b["H"], b["L"], b["C"], sc=b[key], max_hold=max_hold, **kw)
        for x in ts:
            x["pair"] = p
            x["date"] = b["date"][x["i"]]
            if cost:     # 往復でスプレッド 1 回ぶん
                x["ret"] -= SPREAD[p] * pip(p) / x["entry"] * 100
                x["win"] = x["ret"] > 0
        allt += ts
    return allt


def by_era(ts, indent="  "):
    for name, a, b in ERAS:
        sub = [x for x in ts if a <= x["date"] < b]
        print(f"{indent}{name:8s} {summary(sub)}")


def main():
    RAW = load_all(raw=True)
    D = load_all()
    for p in PAIRS:
        print(p, "本数", len(D[p]["C"]))

    print("\n== 組み直す前（旧検証と同じ扱い）・コスト込み・期限15日 ==")
    t = run(RAW)
    print("全期間", summary(t)); by_era(t)

    print("\n== M1+M5 組み直した日足（東京9時締め）・コスト込み・期限15日 ==")
    base = run(D)
    print("全期間", summary(base)); by_era(base)
    print("  コスト無し", summary(run(D, cost=False)))

    print("\n== ペア別（組み直し後・コスト込み）==")
    for p in PAIRS:
        sub = [x for x in base if x["pair"] == p]
        rec = [x for x in sub if x["date"] >= dt.date(2021, 9, 1)]
        print(f"  {p} {summary(sub)}   直近5年 {summary(rec)}")

    print("\n== M2 保有期限（組み直し後・コスト込み）==")
    for mh in (5, 10, 15, 30, None):
        ts = run(D, max_hold=mh)
        tm = sum(1 for x in ts if x["how"] == "time")
        hold = statistics.median([x["j"] - x["i"] for x in ts])
        print(f"  期限{mh}: {summary(ts)}  時間切れ{tm/len(ts)*100:.0f}% 保有日数中央値{hold}")
        by_era(ts, "      ")

    print("\n== M3 ECB の参照レートでサイン（2011年以降・翌朝9時に入る）==")
    agree = tot = 0
    for p in PAIRS:
        b = D[p]
        e = load_ecb(p)
        ed = sorted(e)
        esc = logic.score_series([e[x] for x in ed])
        # ECB(D) は D の 16 時(CET)に出る → 次の東京 9 時（日付 > D の最初の足）で入る
        m = []
        for x in b["date"]:
            k = bisect.bisect_left(ed, x) - 1
            m.append(esc[k] if k >= 0 else None)
        b["sc_ecb"] = m
        for i in range(200, len(b["C"])):
            if b["date"][i] < dt.date(2011, 1, 1) or m[i] is None:
                continue
            tot += 1
            agree += logic.direction(b["sc"][i]) == logic.direction(m[i])
    print(f"  毎日の向きの一致 {agree/tot*100:.1f}%")
    et = [x for x in run(D, key="sc_ecb") if x["date"] >= dt.date(2011, 1, 1)]
    print("  ECB サイン", summary(et)); by_era(et)


if __name__ == "__main__":
    main()
