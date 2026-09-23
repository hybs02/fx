# -*- coding: utf-8 -*-
"""毎朝 GitHub Actions が走らせて data.json を作る（スマホはそれを表示するだけ）。

  1. 11 ペアの日足（2004年〜）と 1 時間足（3ヶ月）を Yahoo から取る（キー不要）
  2. 日足を「東京 9 時締め」に並べ直し、今朝 9 時（UTC 0 時）の値を 1 時間足から足す
  3. RSI の判定・損切り幅・翌朝のサイン価格・22 年分の検証成績を計算して data.json に書く

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
NO_BAR = {(12, 25), (1, 1)}   # 市場がほぼ止まる日。今朝の値を作らない


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


def load(p, use_cache):
    if use_cache:
        cd = os.path.join(HERE, "research", "cache")
        return (json.load(io.open(os.path.join(cd, f"yahoo_d_{p}.json"))),
                json.load(io.open(os.path.join(cd, f"yahoo_h_{p}.json"))))
    now = int(time.time())
    d = yahoo(p, "1d", f"period1=1072915200&period2={now}")
    h = yahoo(p, "60m", "range=3mo")
    return d, h


def wait_for_morning():
    """GitHub の定時実行は混むと 1〜2 時間遅れる（us-stocks では毎回約 2 時間遅れ）。
    そこで早朝（日本の 6〜8 時）に起動しておき、UTC 0 時 1 分（日本の 9:01）まで待ってから計算する。
    遅れて 0 時を過ぎてから起動した時は待たない。金曜の夜（翌日が土曜）は待たない。"""
    now = dt.datetime.now(dt.timezone.utc)
    if now.hour < 18 or now.weekday() in (4, 5):
        return
    target = (now + dt.timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
    wait = (target - now).total_seconds()
    print(f"朝 9 時（UTC 0 時）まで {wait / 60:.0f} 分待ちます", flush=True)
    time.sleep(wait)


def wait_for_snapshot():
    """今朝 9 時の 1 時間足（UTC 23 時台）がまだ出ていなければ、1 分おきに最大 15 分待つ（ドル円で確かめる）"""
    now = dt.datetime.now(dt.timezone.utc)
    if now.weekday() >= 5 or (now.month, now.day) in NO_BAR:
        return
    t0 = int(dt.datetime(now.year, now.month, now.day, tzinfo=dt.timezone.utc).timestamp())
    for k in range(15):
        try:
            if t0 - 3600 in yahoo("USDJPY", "60m", "range=1d")["t"]:
                return
        except Exception:
            pass
        print("  9 時の値がまだ無いので 1 分待つ", flush=True)
        time.sleep(60)


def london_date(t):
    return (dt.datetime.fromtimestamp(t, dt.timezone.utc) + dt.timedelta(hours=3)).date()


def add_weekdays(d, n):
    while n:
        d += dt.timedelta(days=1)
        if d.weekday() < 5 and (d.month, d.day) not in NO_BAR:
            n -= 1
    return d


def daily_bars(d, h, now):
    """確定した日足（UTC の日付が今日より前）＋ 今朝 9 時の値（1 時間足の 23 時台の終値）"""
    today = now.date()
    dates, o, hi, lo, c = [], [], [], [], []
    for t, a, b, e, f in zip(d["t"], d["o"], d["h"], d["l"], d["c"]):
        x = london_date(t)
        if x >= today:              # 進行中の足（夏時間なら明日の日付の足も）は使わない
            continue
        if dates and dates[-1] == x:
            continue
        dates.append(x); o.append(a); hi.append(b); lo.append(e); c.append(f)
    snap = None
    if today.weekday() < 5 and (today.month, today.day) not in NO_BAR and dates and dates[-1] < today:
        t0 = int(dt.datetime(today.year, today.month, today.day, tzinfo=dt.timezone.utc).timestamp())
        hm = dict(zip(h["t"], h["c"]))
        if t0 - 3600 in hm:
            snap = hm[t0 - 3600]
            dates.append(today); o.append(snap); hi.append(snap); lo.append(snap); c.append(snap)
    return logic.make_bars(dates, o, hi, lo, c), snap is not None


def resample_rsi(h, hours):
    """1 時間足を UTC の hours 時間ごとに束ねた終値で RSI(14) と短期・長期の向き"""
    blocks = {}
    for t, c in zip(h["t"], h["c"]):
        blocks[t // (hours * 3600)] = c      # 各区切りの最後の終値
    cl = [blocks[k] for k in sorted(blocks)]
    r = logic.rsi_series(cl)
    s5, s25 = logic.sma_series(cl, 5), logic.sma_series(cl, 25)
    if r[-1] is None or s25[-1] is None:
        return None
    return {"rsi": round(r[-1], 1), "up": s5[-1] > s25[-1]}


def r5(x, p):
    return round(x, 3 if p.endswith("JPY") else 5)


def main():
    use_cache = "--cache" in sys.argv
    if not use_cache:
        wait_for_morning()
        wait_for_snapshot()
    now = dt.datetime.now(dt.timezone.utc)
    if use_cache:
        now = dt.datetime(2026, 9, 23, 3, 0, tzinfo=dt.timezone.utc)
    pairs, all_trades = {}, []
    latest = None
    for p in PAIRS:
        d, h = load(p, use_cache)
        b, has_snap = daily_bars(d, h, now)
        C, H, L, D = b["C"], b["H"], b["L"], b["date"]
        n = len(C)
        sig, rsi = logic.signals(C)
        _, ag, al = logic.rsi_state(C)
        i = n - 1
        latest = max(latest or D[i], D[i])
        a = logic.atr_at(H, L, C, i)
        trades = logic.backtest(b, sig, cost=SPREAD[p] * pip(p))
        for t in trades:
            t["pair"] = p; t["date"] = D[t["i"]].isoformat(); t["xdate"] = D[t["j"]].isoformat()
        all_trades += trades
        tb, ts = logic.trigger_prices(C, ag, al, i)
        # 直近 5 本以内に出たサイン＝まだ手仕舞い日が来ていない（または今日が手仕舞い日）の取引
        active = []
        for k in range(max(logic.WARMUP, n - 1 - logic.HOLD), n):
            if not sig[k]:
                continue
            ak = logic.atr_at(H, L, C, k)
            stop = C[k] - sig[k] * logic.SL_ATR * ak
            hit = any((L[j] <= stop) if sig[k] == 1 else (H[j] >= stop) for j in range(k + 1, n))
            active.append({"date": D[k].isoformat(), "dir": sig[k], "entry": r5(C[k], p), "stop": r5(stop, p),
                           "exit": add_weekdays(D[k], logic.HOLD).isoformat(), "stopped": hit,
                           "bars": n - 1 - k})
        bb = logic.boll_at(C, i)
        s5, s25 = logic.sma_series(C, 5)[i], logic.sma_series(C, 25)[i]
        mc = logic.macd_at(C)
        st = logic.stats(trades)
        pairs[p] = {
            "date": D[i].isoformat(), "fresh": has_snap,
            "price": r5(C[i], p),
            "live": {"p": r5(h["c"][-1], p), "t": h["t"][-1]} if h["t"] else None,
            "rsi": round(rsi[i], 1), "rsiPrev": round(rsi[i - 1], 1),
            "sig": sig[i], "atr": r5(a, p), "atrPips": round(a / pip(p), 1),
            "stop": r5(C[i] - sig[i] * logic.SL_ATR * a, p) if sig[i] else None,
            "exit": add_weekdays(D[i], logic.HOLD).isoformat() if sig[i] else None,
            "trig": {"buy": r5(tb, p) if tb else None, "sell": r5(ts, p) if ts else None},
            "active": active,
            "chart": {"d": [x.isoformat() for x in D[-90:]], "c": [r5(x, p) for x in C[-90:]],
                      "r": [round(x, 1) for x in rsi[-90:]]},
            "ref": {"bb": round((C[i] - bb[0]) / (bb[2] - bb[0]) * 100) if bb and bb[2] > bb[0] else None,
                    "ma": (1 if s5 > s25 else -1) if s25 else None,
                    "macd": (1 if mc[0] > mc[1] else -1) if mc else None,
                    "dev25": round((C[i] - s25) / s25 * 100, 2) if s25 else None,
                    "h4": resample_rsi(h, 4), "h8": resample_rsi(h, 8)},
            "stats": st,
            "last": [{"d": t["date"], "x": t["xdate"], "dir": t["dir"], "ret": round(t["ret"], 2), "how": t["how"]}
                     for t in trades[-8:]][::-1],
        }
        print(p, D[i], "今朝の値" if has_snap else "（今朝の値なし）", "RSI", round(rsi[i], 1), "サイン", sig[i], flush=True)

    def st_between(a, z):
        return logic.stats([t for t in all_trades if a <= t["date"] < z])

    years = {}
    for t in all_trades:
        years.setdefault(t["date"][:4], []).append(t)
    one_year_ago = (now.date() - dt.timedelta(days=365)).isoformat()
    out = {
        "updated": now.astimezone(JST).strftime("%Y-%m-%d %H:%M"),
        "latest": latest.isoformat(),
        "rule": {"rsiN": logic.RSI_N, "buyAt": logic.BUY_AT, "sellAt": logic.SELL_AT, "slAtr": logic.SL_ATR,
                 "hold": logic.HOLD, "deadline": logic.ENTRY_DEADLINE},
        "stats": {
            "all": logic.stats(all_trades),
            "buy": logic.stats([t for t in all_trades if t["dir"] == 1]),
            "sell": logic.stats([t for t in all_trades if t["dir"] == -1]),
            "year1": st_between(one_year_ago, "2100-01-01"),
            "eras": [{"name": nm, **(st_between(a, z) or {})} for nm, a, z in ERAS],
            "years": [{"y": y, "n": len(v), "sum": round(sum(t["ret"] for t in v), 1),
                       "pf": (logic.stats(v) or {}).get("pf")} for y, v in sorted(years.items())],
            "from": min(t["date"] for t in all_trades)[:4],
        },
        "recent": [{"p": t["pair"], "d": t["date"], "x": t["xdate"], "dir": t["dir"], "ret": round(t["ret"], 2),
                    "how": t["how"]} for t in sorted(all_trades, key=lambda t: t["date"])[-24:]][::-1],
        "pairs": pairs,
    }
    io.open(os.path.join(HERE, "data.json"), "w", encoding="utf-8").write(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    s = out["stats"]["all"]
    print(f"完了: {s['n']}回 勝率{s['wr']}% PF{s['pf']}  最新の足 {out['latest']}", flush=True)


if __name__ == "__main__":
    main()
