# -*- coding: utf-8 -*-
"""検証スクリプト共通：キャッシュの読み込みと集計"""
import io, json, os, sys, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import logic  # noqa: E402
import legacy_logic  # noqa: E402  旧規則（比較用）

PAIRS = ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "NZDJPY", "CADJPY", "CHFJPY",
         "EURUSD", "GBPUSD", "AUDUSD", "EURGBP"]
# DMM FX の原則固定スプレッド（pips・公式 fx.dmm.com/fx/aboutfx/spread/ 2026-09-18 現在）。
# 固定なのはコアタイム 9:00〜翌5:00 だけ。朝5〜9時は大きく広がる。
SPREAD = {"USDJPY": 0.2, "EURJPY": 0.4, "GBPJPY": 0.9, "AUDJPY": 0.5, "NZDJPY": 0.7,
          "CADJPY": 0.6, "CHFJPY": 0.8, "EURUSD": 0.3, "GBPUSD": 1.0, "AUDUSD": 0.4, "EURGBP": 1.0}


def pip(p):
    return 0.01 if p.endswith("JPY") else 0.0001


def london_date(t):
    return (dt.datetime.utcfromtimestamp(t + 3 * 3600)).date()


def load_daily(p, drop_last=True):
    d = json.load(io.open(os.path.join(HERE, "cache", f"yahoo_d_{p}.json")))
    keys = ("t", "o", "h", "l", "c")
    if drop_last:           # 最後の足は進行中
        for k in keys:
            d[k] = d[k][:-1]
    # 異常値（高値<安値、ゼロ）を除く
    ok = [i for i in range(len(d["t"])) if d["l"][i] > 0 and d["h"][i] >= d["l"][i]]
    for k in keys:
        d[k] = [d[k][i] for i in ok]
    d["date"] = [london_date(t) for t in d["t"]]
    return d


def load_bars(p, drop_last=True):
    """検証用の日足（東京 9 時締めに並べ直したもの）。作り方は logic.make_bars と同じ＝アプリと同じ"""
    d = load_daily(p, drop_last)
    return logic.make_bars(d["date"], d["o"], d["h"], d["l"], d["c"])


def load_hourly(p):
    return json.load(io.open(os.path.join(HERE, "cache", f"yahoo_h_{p}.json")))


def load_ecb(p):
    d = json.load(io.open(os.path.join(HERE, "cache", f"ecb_{p}.json")))
    return {dt.date.fromisoformat(a): b for a, b in zip(d["d"], d["c"])}


def summary(trades):
    s = logic.stats(trades)
    if not s:
        return "  (取引なし)"
    pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
    return f"n={s['n']:4d} 勝率{s['wr']:5.1f}% 期待値{s['exp']:+.3f}% PF{pf}"


def pf_of(trades):
    s = logic.stats(trades)
    return s["pf"] if s else float("nan")
