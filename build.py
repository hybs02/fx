# -*- coding: utf-8 -*-
"""GitHub Actions が定時に走らせて data.json を作る（スマホはそれを表示するだけ）。

  1. ドル円の 1時間足（2年）と日足（2004年〜）、ドル指数 DXY の 1時間足と日足、
     米 13 週国債の利回り（スワップの計算用）を Yahoo から取る（キー不要）
  2. 1時間ごとに『その時刻で締めた日足』で RSI を計算し、しきい値を越えた最初の時刻をサインにする
     （判定の時刻を固定しない。いつ開いても最新）。行きすぎが円だけの動きでなく、ドル全体の動きなら入らない
  3. 損切り幅・次の1時間のサイン価格・スワップの目安・検証成績を data.json に書く

使い方:  python build.py            （ネットから取る）
         python build.py --cache    （research/cache の保存データで作る・動作確認用）
"""
import datetime as dt, io, json, os, sys, time, urllib.request
import logic

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
PIP = 0.01
SPREAD = 0.2           # DMM FX のドル円の原則固定スプレッド（銭・公式 2026-09-18 現在）。検証成績から差し引く
COST = SPREAD * PIP
ERAS = [("2005〜10年", "2004-01-01", "2011-01-01"), ("2011〜14年", "2011-01-01", "2015-01-01"),
        ("2015〜18年", "2015-01-01", "2019-01-01"), ("2019〜21年", "2019-01-01", "2021-09-01"),
        ("直近5年", "2021-09-01", "2100-01-01")]
DELAYS = [0, 3, 6, 8, 12, 24]
JST = dt.timezone(dt.timedelta(hours=9))


def get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))


def yahoo(sym, interval, extra):
    d = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval={interval}&{extra}")
    r = d["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = {"t": [], "o": [], "h": [], "l": [], "c": []}
    for i, t in enumerate(r["timestamp"]):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c) or l <= 0 or h < l:
            continue
        out["t"].append(t); out["o"].append(o); out["h"].append(h); out["l"].append(l); out["c"].append(c)
    return out


def retry(fn, tries=3):
    for k in range(tries):
        try:
            return fn()
        except Exception as e:
            err = e
            time.sleep(5 * (k + 1))
    raise err


def load(use_cache):
    """1時間足・日足・米金利・ドル指数（1時間足と日足）。どれか取れなければ例外（main が前回の結果を残す）"""
    if use_cache:
        cd = os.path.join(HERE, "research", "cache")
        rd = lambda n: json.load(io.open(os.path.join(cd, n)))
        return (rd("yahoo_h_USDJPY.json"), rd("yahoo_d_USDJPY.json"), rd("yahoo_IRX.json"),
                {"h": rd("yahoo_h_DXY.json"), "d": rd("yahoo_DXY.json")})
    now = int(time.time())
    span = f"period1=1072915200&period2={now}"
    tc = lambda x: {"t": x["t"], "c": x["c"]}
    h = retry(lambda: yahoo("JPY=X", "60m", "range=730d"))
    d = retry(lambda: yahoo("JPY=X", "1d", span))
    irx = retry(lambda: yahoo("%5EIRX", "1d", span))
    dxy = {"h": tc(retry(lambda: yahoo("DX-Y.NYB", "60m", "range=730d"))), "d": tc(retry(lambda: yahoo("DX-Y.NYB", "1d", span)))}
    return h, d, tc(irx), dxy


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


def rp(x):
    return None if x is None else round(x, 3)


def compute(hr, d, irx, dxy, now):
    nowts = now.timestamp()
    # 終わった1時間足だけで判定する（進行中の足は「いまの値」としてだけ使う）
    keep = [i for i, t in enumerate(hr["t"]) if t + 3600 <= nowts]
    h = {k: [hr[k][i] for i in keep] for k in ("t", "o", "h", "l", "c")}
    if len(h["t"]) < 24 * 5 * 40:
        raise ValueError(f"1時間足が少なすぎる（{len(h['t'])}本）")
    ph = logic.phase_series(h["t"], h["h"], h["l"], h["c"])
    st = logic.rolling_state(ph)
    ev = logic.rolling_events(st)
    # 円だけの動き（YEN_N 日前と比べたドル円の％ − ドル指数の％）。ドル全体の動きで行きすぎたサインは入らない
    dxh = dxy["h"]

    def yen_at(t):
        s, k = ph[st[t]["hh"]], st[t]["k"]
        n = logic.YEN_N
        uj, dx, dx0 = s["C"][k], logic.asof(dxh, t), logic.asof(dxh, s["t"][k - n])
        return {"move": logic.yen_move(uj, s["C"][k - n], dx, dx0), "uj": (uj / s["C"][k - n] - 1) * 100,
                "dxy": (dx / dx0 - 1) * 100 if dx and dx0 else None}
    for e in ev:
        e["yen"] = yen_at(e["t"])
        e["ok"] = logic.yen_ok(e["dir"], e["yen"]["move"])
    evok = [e for e in ev if e["ok"]]

    def roll_at(delay):
        out = logic.rolling_backtest(h, ph, st, evok, cost=COST, delay=delay)
        for x in out:
            x["swap"] = logic.swap_pct(irx, x["te"], x["tx"], x["dir"])
            x["ret"] += x["swap"]
            x["R"] = x["ret"] / (logic.SL_ATR * st[x["t"]]["atr"] / x["entry"] * 100)   # 損益÷損切り幅
        return out
    roll = roll_at(0)
    delay = [{"h": k, **(logic.stats(roll_at(k)) or {})} for k in DELAYS]

    tlast = max(st)
    cur = st[tlast]
    # 直近 ENTRY_LIMIT_H 時間以内に越えた（同じ山の2回目でない・DMM が開いている時刻の）サイン
    sig = next((e for e in reversed(ev) if e["fresh"] and logic.dmm_open(e["t"])
                and nowts - e["t"] <= logic.ENTRY_LIMIT_H * 3600), None)
    # 直近 8 日のサイン（その時刻に入った場合の手仕舞い前の取引の目安）
    end = {x + 3600: i for i, x in enumerate(h["t"])}
    active = []
    for e in evok:
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
        active.append({"t": e["t"], "dir": e["dir"], "entry": rp(en), "stop": rp(stop), "exit": tx,
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
    live = hr["c"][-1] if hr["t"] else cur["c"]

    # 22年の検証（朝9時締めの日足）
    b = daily_bars(d, now)
    dsig, _ = logic.signals(b["C"])
    bts = lambda i: dt.datetime.combine(b["date"][i], dt.time(), dt.timezone.utc).timestamp()
    n = logic.YEN_N
    dsig = [x if not x or i < n or logic.yen_ok(x, logic.yen_move(b["C"][i], b["C"][i - n], logic.asof(dxy["d"], bts(i)),
                                                                   logic.asof(dxy["d"], bts(i - n)))) else 0
            for i, x in enumerate(dsig)]
    lt = logic.backtest(b, dsig, cost=COST)
    for x in lt:
        x["date"] = b["date"][x["i"]].isoformat()
        x["t0"] = dt.datetime.combine(b["date"][x["i"]], dt.time(), dt.timezone.utc).timestamp()
        x["t1"] = dt.datetime.combine(b["date"][x["j"]], dt.time(), dt.timezone.utc).timestamp()
        x["ret"] += logic.swap_pct(irx, x["t0"], x["t1"], x["dir"])
        x["R"] = x["ret"] / (logic.SL_ATR * x["atr"] / x["entry"] * 100)

    def between(a, z):
        return logic.stats([t for t in lt if a <= t["date"] < z])
    years = {}
    for t in lt:
        years.setdefault(t["date"][:4], []).append(t)

    # いまのスワップの目安（1万通貨・1日・円）。金利差から計算（DMM の実際の値とは数円ずれる）
    diff = logic.rate_diff(irx, nowts)
    swap = {"diff": round(diff, 2), "boj": logic.BOJ_RATE[-1][1],
            "buy": round(diff / 100 / 365 * live * 10000),
            "sell": round(-(diff + logic.SELL_EXTRA) / 100 / 365 * live * 10000)}

    sa = st[sig["t"]] if sig else None
    return {
        "t": tlast, "price": rp(cur["c"]), "live": {"p": rp(live), "t": hr["t"][-1]},
        "rsi": round(cur["rsi"], 1), "rsiPrev": round(st[prev_t]["rsi"], 1),
        "atr": rp(cur["atr"]), "atrPips": round(cur["atr"] / PIP, 1),
        "sig": {"dir": sig["dir"], "t": sig["t"], "from": round(sig["from"], 1), "to": round(sig["to"], 1),
                "price": rp(sa["c"]), "atr": rp(sa["atr"]), "atrPips": round(sa["atr"] / PIP, 1),
                "exit": logic.exit_time(sig["t"]), "yenOk": sig["ok"],
                "yen": {k: None if v is None else round(v, 2) for k, v in sig["yen"].items()}} if sig else None,
        "yen": {k: None if v is None else round(v, 2) for k, v in yen_at(tlast).items()},
        "trig": {"buy": rp(tb), "sell": rp(ts)},
        "active": active,
        "swap": swap,
        "chart": {"t": s["t"][max(0, k - 89):k + 1], "c": [rp(x) for x in C[-90:]],
                  "r": [round(x, 1) for x in rs[-90:]],
                  "ev": [{"t": e["t"], "dir": e["dir"]} for e in evok if e["fresh"] and e["t"] >= s["t"][max(0, k - 89)]]},
        "ref": {"bb": round((C[k] - bb[0]) / (bb[2] - bb[0]) * 100) if bb and bb[2] > bb[0] else None,
                "ma": (1 if s5 > s25 else -1) if s25 else None,
                "macd": (1 if mc[0] > mc[1] else -1) if mc else None,
                "dev25": round((C[k] - s25) / s25 * 100, 2) if s25 else None,
                "h4": resample_rsi(h, 4), "h8": resample_rsi(h, 8)},
        "stats": {
            "roll": {**(logic.stats(roll) or {"n": 0}), "from": min(x["t"] for x in roll) if roll else h["t"][0],
                     "buy": logic.stats([t for t in roll if t["dir"] == 1]),
                     "sell": logic.stats([t for t in roll if t["dir"] == -1])},
            "delay": delay,
            # 資金に対する増え方（1回のリスク＝資金の1%あたり。画面で設定のリスク%を掛ける）
            "money": {"roll": logic.equity([{**x, "t1": x["tx"]} for x in roll]), "long": logic.equity(lt)},
            "long": {**logic.stats(lt), "from": min(t["date"] for t in lt)[:4],
                     "buy": logic.stats([t for t in lt if t["dir"] == 1]),
                     "sell": logic.stats([t for t in lt if t["dir"] == -1]),
                     "eras": [{"name": nm, **(between(a, z) or {})} for nm, a, z in ERAS],
                     "years": [{"y": y, "n": len(v), "sum": round(sum(t["ret"] for t in v), 1)}
                               for y, v in sorted(years.items())]},
        },
        "recent": [{"t": x["t"], "tx": x["tx"], "dir": x["dir"], "ret": round(x["ret"], 2), "how": x["how"]}
                   for x in roll[-12:]][::-1],
    }


def main():
    use_cache = "--cache" in sys.argv
    now = dt.datetime.now(dt.timezone.utc)
    if use_cache:
        now = dt.datetime.fromtimestamp(json.load(io.open(os.path.join(HERE, "research", "cache", "yahoo_h_USDJPY.json")))["t"][-1] + 1800, dt.timezone.utc)
    try:
        hr, d, irx, dxy = load(use_cache)
        body = compute(hr, d, irx, dxy, now)
    except Exception as e:
        # 取れなかった時は止まる。data 枝の前回の結果がそのまま残る
        raise SystemExit(f"計算できなかった（前回の data.json を残す）: {e}")
    out = {"updated": now.astimezone(JST).strftime("%Y-%m-%d %H:%M"), "updatedTs": int(now.timestamp()),
           "pair": "USDJPY",
           "rule": {"rsiN": logic.RSI_N, "buyAt": logic.BUY_AT, "sellAt": logic.SELL_AT, "slAtr": logic.SL_ATR,
                    "hold": logic.HOLD, "best": logic.ENTRY_BEST_H, "limit": logic.ENTRY_LIMIT_H, "spread": SPREAD,
                    "yenN": logic.YEN_N},
           **body}
    io.open(os.path.join(HERE, "data.json"), "w", encoding="utf-8").write(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    r, L = out["stats"]["roll"], out["stats"]["long"]
    print(f"{dt.datetime.fromtimestamp(out['t'], JST):%m-%d %H:%M} RSI {out['rsi']} サイン {out['sig']['dir'] if out['sig'] else 0}"
          f" | 1時間ごと {r['n']}回 PF{r.get('pf')} | 22年 {L['n']}回 PF{L['pf']} | スワップ 買い{out['swap']['buy']}円 売り{out['swap']['sell']}円", flush=True)


if __name__ == "__main__":
    main()
