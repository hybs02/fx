# -*- coding: utf-8 -*-
"""検証用データを cache/ に取る。
  yahoo_d_{PAIR}.json   日足 OHLC（取れるだけ過去から）
  yahoo_h_{PAIR}.json   60分足 OHLC（Yahoo の上限 730 日）
  ecb_{PAIR}.json       ECB の参照レート（frankfurter・キー無し版アプリが使っていたもの）
"""
import io, json, os, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
PAIRS = ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "NZDJPY", "CADJPY", "CHFJPY",
         "EURUSD", "GBPUSD", "AUDUSD", "EURGBP"]


def ysym(p):
    return "JPY=X" if p == "USDJPY" else p + "=X"


def get(url):
    for k in range(4):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))
        except Exception as e:
            err = e
            time.sleep(2 * (k + 1))
    raise err


def yahoo(p, interval, rng):
    d = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym(p)}?range={rng}&interval={interval}")
    r = d["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = {"t": [], "o": [], "h": [], "l": [], "c": [], "gmtoffset": r["meta"].get("gmtoffset")}
    for i, t in enumerate(r["timestamp"]):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):
            continue
        out["t"].append(t); out["o"].append(o); out["h"].append(h); out["l"].append(l); out["c"].append(c)
    return out


def ecb(p):
    b, q = p[:3], p[3:]
    d = get(f"https://api.frankfurter.dev/v1/2004-01-01..?base={b}&symbols={q}")
    days = sorted(d["rates"])
    return {"d": days, "c": [d["rates"][x][q] for x in days]}


def main():
    os.makedirs(CACHE, exist_ok=True)
    for p in PAIRS:
        for name, fn in (("yahoo_d", lambda: yahoo(p, "1d", "max")),
                         ("yahoo_h", lambda: yahoo(p, "60m", "730d")),
                         ("ecb", lambda: ecb(p))):
            path = os.path.join(CACHE, f"{name}_{p}.json")
            data = fn()
            io.open(path, "w").write(json.dumps(data, separators=(",", ":")))
            n = len(data.get("t") or data.get("d"))
            print(p, name, n, flush=True)
            time.sleep(0.3)


if __name__ == "__main__":
    main()
