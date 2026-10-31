# -*- coding: utf-8 -*-
"""検証用データを cache/ に取る。
  yahoo_d_{PAIR}.json   日足 OHLC（取れるだけ過去から）
  yahoo_h_{PAIR}.json   60分足 OHLC（Yahoo の上限 730 日）
  ecb_{PAIR}.json       ECB の参照レート（frankfurter）
  yahoo_IRX.json        米 13 週国債の利回り（スワップの計算用）
  yahoo_{X}.json        外の材料の日足の終値（TNX 米10年金利・FVX 米5年金利・VIX・N225 日経平均・GSPC S&P500・DXY ドル指数）
  yahoo_h_DXY.json      ドル指数の60分足の終値（円だけの動きの判定用）
ドル円の規則を選び直すだけなら  python research/fetch.py USDJPY
"""
import io, json, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
PAIRS = ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "NZDJPY", "CADJPY", "CHFJPY",
         "EURUSD", "GBPUSD", "AUDUSD", "EURGBP"]


EXT = {"TNX": "%5ETNX", "FVX": "%5EFVX", "VIX": "%5EVIX", "N225": "%5EN225", "GSPC": "%5EGSPC", "DXY": "DX-Y.NYB"}


def ysym(p):
    return {"USDJPY": "JPY=X", "IRX": "%5EIRX", **EXT}.get(p, p + "=X")


def get(url):
    for k in range(4):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))
        except Exception as e:
            err = e
            time.sleep(2 * (k + 1))
    raise err


def yahoo(p, interval, rng):
    # 日足は range=max だと月足に間引かれるので、2004 年からの期間で頼む
    span = f"period1=1072915200&period2={int(time.time())}" if rng == "max" else f"range={rng}"
    d = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym(p)}?{span}&interval={interval}")
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
    irx = yahoo("IRX", "1d", "max")
    io.open(os.path.join(CACHE, "yahoo_IRX.json"), "w").write(json.dumps({"t": irx["t"], "c": irx["c"]}, separators=(",", ":")))
    print("IRX", len(irx["t"]), flush=True)
    for x in EXT:
        d = yahoo(x, "1d", "max")
        io.open(os.path.join(CACHE, f"yahoo_{x}.json"), "w").write(json.dumps({"t": d["t"], "c": d["c"]}, separators=(",", ":")))
        print(x, len(d["t"]), flush=True)
    d = yahoo("DXY", "60m", "730d")
    io.open(os.path.join(CACHE, "yahoo_h_DXY.json"), "w").write(json.dumps({"t": d["t"], "c": d["c"]}, separators=(",", ":")))
    print("DXY 60m", len(d["t"]), flush=True)
    for p in sys.argv[1:] or PAIRS:
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
