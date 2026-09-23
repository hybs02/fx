# -*- coding: utf-8 -*-
"""サインが同じ日に固まって出る問題（資金管理の見落とし）。

1回あたり「損切りで資金の2%」に抑えても、同じ通貨に同じ向きで賭ける取引を同時に3つ持てば実質6%。
22年（朝9時締めの日足・11ペア）と直近2年（1時間ごとの判定）で、
  ・同時に持つ数・同じ通貨への偏り
  ・資金に対する最大の落ち込み（1回2%のリスクで全部入った場合）
  ・上限を決めた場合（同じ通貨を同じ向きに◯つまで／1回のリスクを同時の数で割る）
を比べる。
"""
import sys, statistics, datetime as dt
from common import PAIRS, SPREAD, pip, load_bars, load_hourly, logic

sys.stdout.reconfigure(encoding="utf-8")
RISK = 2.0


def exposure(pair, d):
    """通貨ごとの向き（+1 買い持ち / -1 売り持ち）"""
    return {pair[:3]: d, pair[3:]: -d}


def simulate(trades, rule):
    """trades: dict(t0, t1, pair, dir, R) を時刻順に。rule で入るか・リスク何%かを決める。
    戻り値: 取った数、合計R×リスク（%）、最大の落ち込み（%・単利）"""
    trades = sorted(trades, key=lambda x: x["t0"])
    open_, eq, peak, mdd, taken, curve = [], 0.0, 0.0, 0.0, 0, []
    events = []
    for x in trades:
        # 期限が来た取引を閉じる
        for o in [o for o in open_ if o["t1"] <= x["t0"]]:
            open_.remove(o)
            eq += o["risk"] * o["R"]
            peak = max(peak, eq); mdd = min(mdd, eq - peak)
        risk = rule(x, open_)
        if not risk:
            continue
        taken += 1
        open_.append({**x, "risk": risk})
    for o in sorted(open_, key=lambda o: o["t1"]):
        eq += o["risk"] * o["R"]; peak = max(peak, eq); mdd = min(mdd, eq - peak)
    return taken, eq, mdd


def rules():
    def all_in(x, open_):
        return RISK

    def cap_ccy(k):
        def f(x, open_):
            ex = exposure(x["pair"], x["dir"])
            for c, s in ex.items():
                same = sum(1 for o in open_ if exposure(o["pair"], o["dir"]).get(c) == s)
                if same >= k:
                    return 0
            return RISK
        return f

    def split(x, open_):
        # 同じ日（24時間以内）に出た同じ通貨・同じ向きのサインがあれば、そのぶん1回のリスクを割る
        ex = exposure(x["pair"], x["dir"])
        same = max(sum(1 for o in open_ if exposure(o["pair"], o["dir"]).get(c) == s and x["t0"] - o["t0"] < 86400)
                   for c, s in ex.items())
        return RISK / (same + 1)

    def total_cap(maxrisk):
        def f(x, open_):
            used = sum(o["risk"] for o in open_)
            return RISK if used + RISK <= maxrisk else 0
        return f
    return [("全部入る（1回2%）", all_in), ("同じ通貨・同じ向きは1つまで", cap_ccy(1)),
            ("同じ通貨・同じ向きは2つまで", cap_ccy(2)), ("同時のリスク合計6%まで", total_cap(6.0)),
            ("同じ日の同じ向きはリスクを分ける", split)]


def daily_trades():
    out = []
    for p in PAIRS:
        b = load_bars(p)
        sig, _ = logic.signals(b["C"])
        for x in logic.backtest(b, sig, cost=SPREAD[p] * pip(p)):
            sl_pct = logic.SL_ATR * x["atr"] / x["entry"] * 100
            t0 = dt.datetime.combine(b["date"][x["i"]], dt.time()).timestamp()
            t1 = dt.datetime.combine(b["date"][x["j"]], dt.time()).timestamp()
            out.append({"pair": p, "dir": x["dir"], "t0": t0, "t1": t1, "R": x["ret"] / sl_pct})
    return out


def hourly_trades():
    out = []
    for p in PAIRS:
        h = load_hourly(p)
        ph = logic.phase_series(h["t"], h["h"], h["l"], h["c"])
        st = logic.rolling_state(ph); ev = logic.rolling_events(st)
        for x in logic.rolling_backtest(h, ph, st, ev, cost=SPREAD[p] * pip(p)):
            sl_pct = logic.SL_ATR * st[x["t"]]["atr"] / x["entry"] * 100
            out.append({"pair": p, "dir": x["dir"], "t0": x["t"], "t1": x["tx"], "R": x["ret"] / sl_pct})
    return out


def report(name, tr):
    print(f"\n== {name}：{len(tr)}回 ==")
    # 入った時点で、同じ通貨に同じ向きで何本持っていることになるか
    tr = sorted(tr, key=lambda x: x["t0"])
    worst = []
    for i, x in enumerate(tr):
        ex = exposure(x["pair"], x["dir"])
        n = max(sum(1 for o in tr[:i] if o["t1"] > x["t0"] and exposure(o["pair"], o["dir"]).get(c) == s) for c, s in ex.items())
        worst.append(n + 1)
    import collections
    print("   入った時に同じ通貨・同じ向きの取引が何本になるか:", dict(sorted(collections.Counter(worst).items())))
    for nm, f in rules():
        taken, eq, mdd = simulate(tr, f)
        print(f"   {nm:22s} 取った{taken:4d}回  合計{eq:+7.1f}%  最大の落ち込み{mdd:6.1f}%  落ち込みに対する利益 {eq / -mdd if mdd else float('nan'):.1f}")


if __name__ == "__main__":
    report("22年（朝9時締めの日足）", daily_trades())
    report("直近2年（1時間ごとの判定）", hourly_trades())
