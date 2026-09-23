# -*- coding: utf-8 -*-
"""1時間ごとに GitHub Actions が走らせて data.json を作る（スマホはそれを表示するだけ）。

  1. 11 ペアの 1時間足（2年）と日足（2004年〜）を Yahoo から取る（キー不要）
  2. 1時間ごとに『その時刻で締めた日足』で RSI を計算し、しきい値を越えた最初の時刻をサインにする
     （判定の時刻を固定しない。いつ開いても最新）
  3. 損切り幅・次の1時間のサイン価格・検証成績を data.json に書く

使い方:  python build.py            （ネットから取る）
         python build.py --cache    （research/cache の保存データで作る・動作確認用）
"""
import datetime as dt, io, json, os, sys, time, urllib.request
import logic

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
PAIRS = ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "NZDJPY", "CADJPY", "CHFJPY",
         "EURUSD", "GBPUSD", "AUDUSD", "EURGBP"]
# DMM FX の原則固定スプレッド（pips・公式 2026-09-18 現在）。検証成績から差し引く
SPREAD = {"USDJPY": 0.2, "EURJPY": 0.4, "GBPJPY": 0.9, "AUDJPY": 0.5, "NZDJPY": 0.7,
          "CADJPY": 0.6, "CHFJPY": 0.8, "EURUSD": 0.3, "GBPUSD": 1.0, "AUDUSD": 0.4, "EURGBP": 1.0}
ERAS = [("2004〜10年", "2004-01-01", "2011-01-01"), ("2011〜14年", "2011-01-01", "2015-01-01"),
        ("2015〜18年", "2015-01-01", "2019-01-01"), ("2019〜21年", "2019-01-01", "2021-09-01"),
        ("直近5年", "2021-09-01", "2100-01-01")]
JST = dt.timezone(dt.timedelta(hours=9))
# research/study_cut.py と study_cut_fred.py の結果（データが変わらないので固定で載せる）
# 入るのが遅れた時の PF（DMM の取引時間だけ・出口は入った1週間後。research/study_real.py の R1 と同じ計算）
DELAY = [{"h": 0, "pf": 1.92}, {"h": 2, "pf": 1.89}, {"h": 3, "pf": 1.74}, {"h": 6, "pf": 1.64},
         {"h": 8, "pf": 1.49}, {"h": 12, "pf": 1.42}, {"h": 24, "pf": 1.00}]
CUTS = [{"name": "朝9時（Yahoo）", "pf": 1.51, "eras": [1.66, 1.21, 1.55, 1.55]},
        {"name": "欧州の昼 14:15（ECB）", "pf": 1.23, "eras": [1.23, 1.11, 1.12, 1.37]},
        {"name": "NYの昼（FRB）", "pf": 1.21, "eras": [1.71, 0.83, 1.30, 1.00]}]


def pip(p):
    return 0.01 if p.endswith("JPY") else 0.0001


def ysym(p):
    return "JPY=X" if p == "USDJPY" else p + "=X"


def get(url, tries=4):
    for k in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))
        except Exception as e:
            err = e
            time.sleep(3 * (k + 1))
    raise err


def yahoo(p, interval, extra):
    d = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym(p)}?interval={interval}&{extra}")
    r = d["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = {"t": [], "o": [], "h": [], "l": [], "c": []}
    for i, t in enumerate(r["timestamp"]):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c) or l <= 0 or h < l:
            continue
        out["t"].append(t); out["o"].append(o); out["h"].append(h); out["l"].append(l); out["c"].append(c)
    return out


def london_date(t):
    return (dt.datetime.fromtimestamp(t, dt.timezone.utc) + dt.timedelta(hours=3)).date()


def daily_bars(d, now):
    """22年の検証用：確定した日足だけ（東京9時締めに並べ直す）"""
    today = now.date()
    dates, o, hi, lo, c = [], [], [], [], []
    for t, a, b, e, f in zip(d["t"], d["o"], d["h"], d["l"], d["c"]):
        x = london_date(t)
        if x >= today or (dates and dates[-1] == x):
            continue
        dates.append(x); o.append(a); hi.append(b); lo.append(e); c.append(f)
    return logic.make_bars(dates, o, hi, lo, c)


def resample_rsi(h, hours):
    """1時間足を UTC の hours 時間ごとに束ねた終値で RSI(14) と短期・長期の向き"""
    blocks = {}
    for t, c in zip(h["t"], h["c"]):
        blocks[t // (hours * 3600)] = c
    cl = [blocks[k] for k in sorted(blocks)]
    r = logic.rsi_series(cl)
    s5, s25 = logic.sma_series(cl, 5), logic.sma_series(cl, 25)
    if r[-1] is None or s25[-1] is None:
        return None
    return {"rsi": round(r[-1], 1), "up": s5[-1] > s25[-1]}


def rp(x, p):
    return None if x is None else round(x, 3 if p.endswith("JPY") else 5)


def build_pair(p, use_cache, now):
    """1ペアぶんの計算。取得や計算に失敗したら例外を投げる（main が前回の値で埋める）"""
    nowts = now.timestamp()
    d, hr = load(p, use_cache)
    cost = SPREAD[p] * pip(p)
    # 終わった1時間足だけで判定する（進行中の足は「いまの値」としてだけ使う）
    keep = [i for i, t in enumerate(hr["t"]) if t + 3600 <= nowts]
    h = {k: [hr[k][i] for i in keep] for k in ("t", "o", "h", "l", "c")}
    if len(h["t"]) < 24 * 5 * 40:
        raise ValueError(f"{p}: 1時間足が少なすぎる（{len(h['t'])}本）")
    ph = logic.phase_series(h["t"], h["h"], h["l"], h["c"])
    st = logic.rolling_state(ph)
    ev = logic.rolling_events(st)
    roll = logic.rolling_backtest(h, ph, st, ev, cost=cost)
    for x in roll:
        x["pair"] = p
        x["R"] = x["ret"] / (logic.SL_ATR * st[x["t"]]["atr"] / x["entry"] * 100)   # 損益÷損切り幅
    tlast = max(st)
    cur = st[tlast]
    # 直近 ENTRY_LIMIT_H 時間以内に越えた（同じ山の2回目でない・DMM が開いている時刻の）サイン
    sig = next((e for e in reversed(ev) if e["fresh"] and logic.dmm_open(e["t"])
                and nowts - e["t"] <= logic.ENTRY_LIMIT_H * 3600), None)
    # 直近 8 日のサイン（その時刻に入った場合の手仕舞い前の取引の目安）
    end = {x + 3600: i for i, x in enumerate(h["t"])}
    active = []
    for e in ev:
        if not e["fresh"] or not logic.dmm_open(e["t"]) or nowts - e["t"] > 8 * 86400:
            continue
        tx = logic.exit_time(e["t"])
        en = st[e["t"]]["c"]
        stop = en - e["dir"] * logic.SL_ATR * st[e["t"]]["atr"]
        hit = None
        for x in range(e["t"] + 3600, int(min(tx, tlast)) + 1, 3600):
            i = end.get(x)
            if i is not None and ((h["l"][i] <= stop) if e["dir"] == 1 else (h["h"][i] >= stop)):
                hit = x
                break
        active.append({"t": e["t"], "dir": e["dir"], "entry": rp(en, p), "stop": rp(stop, p), "exit": tx,
                       "stopped": hit, "done": tx <= tlast})
    tb, ts = logic.next_hour_triggers(st, tlast)
    s = ph[cur["hh"]]
    k = cur["k"]
    C = s["C"][:k + 1]
    rs = logic.rsi_series(C)
    bb = logic.boll_at(C, k)
    s5, s25 = logic.sma_series(C, 5)[k], logic.sma_series(C, 25)[k]
    mc = logic.macd_at(C)
    prev_t = max(x for x in st if x < tlast)
    # 22年の検証（朝9時締めの日足）。日足が取れなかった時は None（main が前回の成績を使う）
    lt = None
    if d and d.get("t"):
        b = daily_bars(d, now)
        dsig, _ = logic.signals(b["C"])
        lt = logic.backtest(b, dsig, cost=cost)
        for x in lt:
            x["date"] = b["date"][x["i"]].isoformat()
            x["pair"] = p
            x["t0"] = dt.datetime.combine(b["date"][x["i"]], dt.time(), dt.timezone.utc).timestamp()
            x["t1"] = dt.datetime.combine(b["date"][x["j"]], dt.time(), dt.timezone.utc).timestamp()
            x["R"] = x["ret"] / (logic.SL_ATR * x["atr"] / x["entry"] * 100)
    sa = st[sig["t"]] if sig else None
    entry = {
        "t": tlast, "price": rp(cur["c"], p),
        "live": {"p": rp(hr["c"][-1], p), "t": hr["t"][-1]} if hr["t"] else None,
        "rsi": round(cur["rsi"], 1), "rsiPrev": round(st[prev_t]["rsi"], 1),
        "atr": rp(cur["atr"], p), "atrPips": round(cur["atr"] / pip(p), 1),
        "sig": {"dir": sig["dir"], "t": sig["t"], "from": round(sig["from"], 1), "to": round(sig["to"], 1),
                "price": rp(sa["c"], p), "atr": rp(sa["atr"], p), "atrPips": round(sa["atr"] / pip(p), 1),
                "exit": logic.exit_time(sig["t"])} if sig else None,
        "trig": {"buy": rp(tb, p), "sell": rp(ts, p)},
        "active": active,
        "chart": {"t": s["t"][max(0, k - 89):k + 1], "c": [rp(x, p) for x in C[-90:]],
                  "r": [round(x, 1) for x in rs[-90:]],
                  "ev": [{"t": e["t"], "dir": e["dir"]} for e in ev if e["fresh"] and e["t"] >= s["t"][max(0, k - 89)]]},
        "ref": {"bb": round((C[k] - bb[0]) / (bb[2] - bb[0]) * 100) if bb and bb[2] > bb[0] else None,
                "ma": (1 if s5 > s25 else -1) if s25 else None,
                "macd": (1 if mc[0] > mc[1] else -1) if mc else None,
                "dev25": round((C[k] - s25) / s25 * 100, 2) if s25 else None,
                "h4": resample_rsi(h, 4), "h8": resample_rsi(h, 8)},
        "roll": logic.stats(roll), "long": logic.stats(lt) if lt is not None else None,
        "last": [{"t": x["t"], "tx": x["tx"], "dir": x["dir"], "ret": round(x["ret"], 2), "how": x["how"]}
                 for x in roll[-8:]][::-1],
    }
    return entry, roll, lt


def load(p, use_cache):
    """1時間足（必須）と日足（成績の表示だけに使う・失敗しても続ける）。どちらも数回やり直す"""
    if use_cache:
        cd = os.path.join(HERE, "research", "cache")
        return (json.load(io.open(os.path.join(cd, f"yahoo_d_{p}.json"))),
                json.load(io.open(os.path.join(cd, f"yahoo_h_{p}.json"))))
    now = int(time.time())
    h = retry(lambda: yahoo(p, "60m", "range=730d"))
    try:
        d = retry(lambda: yahoo(p, "1d", f"period1=1072915200&period2={now}"))
    except Exception as e:
        print(f"  {p}: 日足が取れなかった（成績は前回の値を使う）: {e}", flush=True)
        d = None
    return d, h


def retry(fn, tries=3):
    for k in range(tries):
        try:
            return fn()
        except Exception as e:
            err = e
            time.sleep(5 * (k + 1))
    raise err


def main():
    use_cache = "--cache" in sys.argv
    now = dt.datetime.now(dt.timezone.utc)
    if use_cache:
        now = dt.datetime(2026, 9, 23, 3, 30, tzinfo=dt.timezone.utc)
    nowts = now.timestamp()
    # 前回の結果（GitHub Actions では data 枝から取ってくる）。取れなかったペアはこれで埋める
    prev = {}
    if os.path.exists(os.path.join(HERE, "prev.json")):
        try:
            prev = json.load(io.open(os.path.join(HERE, "prev.json"), encoding="utf-8"))
        except Exception:
            prev = {}
    pairs, roll_all, long_all, failed, long_ok = {}, [], [], [], True
    for p in PAIRS:
        try:
            entry, roll, lt = build_pair(p, use_cache, now)
        except Exception as e:
            print(f"{p}: 失敗 {e}", flush=True)
            failed.append(p)
            old = (prev.get("pairs") or {}).get(p)
            if old:
                pairs[p] = {**old, "stale": True}
            continue
        pairs[p] = entry
        roll_all += roll
        if lt is None:
            long_ok = False
        else:
            long_all += lt
        s = entry["sig"]
        print(p, dt.datetime.fromtimestamp(entry["t"], JST).strftime("%m-%d %H:%M"), "RSI", entry["rsi"],
              "サイン", s["dir"] if s else 0, flush=True)
    if len(pairs) < len(PAIRS):
        raise SystemExit(f"取れなかったペアがあり、前回の値も無い: {[p for p in PAIRS if p not in pairs]}")
    if len(failed) == len(PAIRS):
        raise SystemExit("全ペアの取得に失敗（前回の結果をそのまま残す）")

    def between(a, z):
        return logic.stats([t for t in long_all if a <= t["date"] < z])

    years = {}
    for t in long_all:
        years.setdefault(t["date"][:4], []).append(t)
    rsorted = sorted(roll_all, key=lambda x: x["t"])
    if failed or not long_ok:
        # 一部のペアが欠けた成績は他と比べられないので、前回の成績をそのまま使う
        stats, recent = prev.get("stats"), prev.get("recent")
    else:
        stats = {
            "roll": {**logic.stats(roll_all), "from": rsorted[0]["t"] if rsorted else None,
                     "buy": logic.stats([t for t in roll_all if t["dir"] == 1]),
                     "sell": logic.stats([t for t in roll_all if t["dir"] == -1])},
            "delay": DELAY, "cuts": CUTS,
            # 資金に対する増え方（1回のリスク＝資金の1%あたり。画面で設定のリスク%を掛ける）
            "money": {"roll": logic.portfolio([{**x, "t0": x["te"], "t1": x["tx"]} for x in roll_all]),
                      "rollAll": logic.portfolio([{**x, "t0": x["te"], "t1": x["tx"]} for x in roll_all], cap=0),
                      "long": logic.portfolio(long_all), "longAll": logic.portfolio(long_all, cap=0),
                      "cap": logic.MAX_SAME_SIDE},
            "long": {**logic.stats(long_all), "from": min(t["date"] for t in long_all)[:4],
                     "eras": [{"name": nm, **(between(a, z) or {})} for nm, a, z in ERAS],
                     "years": [{"y": y, "n": len(v), "sum": round(sum(t["ret"] for t in v), 1)}
                               for y, v in sorted(years.items())]},
        }
        recent = [{"p": x["pair"], "t": x["t"], "tx": x["tx"], "dir": x["dir"], "ret": round(x["ret"], 2),
                   "how": x["how"]} for x in rsorted[-24:]][::-1]
    if not stats:
        raise SystemExit("成績を計算できず、前回の値も無い")
    out = {
        "updated": now.astimezone(JST).strftime("%Y-%m-%d %H:%M"), "updatedTs": int(nowts),
        "latestT": max(v["t"] for v in pairs.values()),
        "failed": failed,
        "rule": {"rsiN": logic.RSI_N, "buyAt": logic.BUY_AT, "sellAt": logic.SELL_AT, "slAtr": logic.SL_ATR,
                 "hold": logic.HOLD, "best": logic.ENTRY_BEST_H, "limit": logic.ENTRY_LIMIT_H,
                 "maxSame": logic.MAX_SAME_SIDE},
        "stats": stats, "recent": recent, "pairs": pairs,
    }
    io.open(os.path.join(HERE, "data.json"), "w", encoding="utf-8").write(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    r = out["stats"]["roll"]
    print(f"完了: 1時間ごと判定 {r['n']}回 勝率{r['wr']}% PF{r['pf']}  失敗 {failed}", flush=True)


if __name__ == "__main__":
    main()
