# -*- coding: utf-8 -*-
"""判定ロジック（Python 版・アプリの唯一の計算元）。

build.py（GitHub Actions）と research/ の検証スクリプトが共に使う。
以前はスマホの JS が同じ計算をしていたが、2026-09-23 から
「サーバーで計算 → data.json → スマホは表示するだけ」に変えたので、ここが本体。

指標はすべて「その日までの値だけ」で計算する（先読みなし）。
系列を一度だけ走査する形にしてあるが、旧 JS 版の analyze()/backtest() と
1 日ずつ切り出して計算した結果と完全に一致することを research/check_js.py で確認している。
"""
import math

ENTRY_GATE = 3          # 日足スコアがこの値以上（以下）でサイン
SL_ATR = 2.5            # 損切り幅（ATR の倍数）
TP_ATR = 2.5            # 利確幅（ATR の倍数）
MAX_HOLD = 15           # 何日で手仕舞うか（None＝期限なし）
FRESH_ONLY = True       # サインは初日だけ有効
WARMUP = 80


# ---------------- 指標（系列） ----------------
def sma_series(c, n):
    out = [None] * len(c)
    s = 0.0
    for i, v in enumerate(c):
        s += v
        if i >= n:
            s -= c[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def sma_exact(c, i, n):
    """JS の sma() と同じ足し順（誤差まで一致させるため）"""
    s = 0.0
    for k in range(i - n + 1, i + 1):
        s += c[k]
    return s / n


def ema_series(a, n):
    """JS の emaSeries と同じ：先頭 n 個の単純平均から始める。out[k] は a[n-1+k] の時点"""
    if len(a) < n:
        return []
    k = 2 / (n + 1)
    s = 0.0
    for i in range(n):
        s += a[i]
    out = [s / n]
    for i in range(n, len(a)):
        out.append(a[i] * k + out[-1] * (1 - k))
    return out


def rsi_series(c, n=14):
    out = [None] * len(c)
    if len(c) < n + 1:
        return out
    ag = al = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]
        ag += max(d, 0.0)
        al += max(-d, 0.0)
    ag /= n
    al /= n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        ag = (ag * (n - 1) + max(d, 0.0)) / n
        al = (al * (n - 1) + max(-d, 0.0)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def macd_series(c, f=12, s=26, sig=9):
    """各時点の (macd, signal)。JS と同じく長さ s+sig 未満は None"""
    out = [None] * len(c)
    ef = ema_series(c, f)
    es = ema_series(c, s)
    if not es:
        return out
    ef = ef[len(ef) - len(es):]
    ml = [x - y for x, y in zip(ef, es)]          # ml[k] は c[s-1+k] の時点
    sl = ema_series(ml, sig)                       # sl[k] は ml[sig-1+k] の時点
    for k, v in enumerate(sl):
        i = s - 1 + sig - 1 + k
        if i + 1 >= s + sig:
            out[i] = (ml[sig - 1 + k], v)
    return out


def boll(c, i, n=20, k=2):
    if i + 1 < n:
        return None
    w = c[i - n + 1:i + 1]
    mid = 0.0
    for v in w:
        mid += v
    mid /= n
    var = 0.0
    for v in w:
        var += (v - mid) ** 2
    sd = math.sqrt(var / n)
    return (mid - k * sd, mid, mid + k * sd)


# ---------------- スコア ----------------
def score_series(c, detail=False):
    """各日の日足スコア。detail=True なら最終日の内訳も返す"""
    n = len(c)
    rs = rsi_series(c)
    mc = macd_series(c)
    sc = [None] * n
    for i in range(n):
        s = 0
        r = rs[i]
        if r is not None:
            if r <= 30:
                s += 3
            elif r >= 70:
                s -= 3
        bb = boll(c, i)
        if bb:
            if c[i] <= bb[0]:
                s += 2
            elif c[i] >= bb[2]:
                s -= 2
        if i >= 24:
            s5, s25 = sma_exact(c, i, 5), sma_exact(c, i, 25)
            s += 1 if s5 > s25 else -1
        m = mc[i]
        if m:
            s += 1 if m[0] > m[1] else -1
        sc[i] = s
    if not detail:
        return sc
    return sc, explain(c, len(c) - 1, rs, mc)


def explain(c, i, rs=None, mc=None):
    """その日の内訳（画面の「なぜ」に出す行）。点数の付け方は score_series と同じ"""
    rs = rs or rsi_series(c[:i + 1])
    mc = mc or macd_series(c[:i + 1])
    price = c[i]
    rows = []
    r = rs[i]
    if r is not None:
        if r <= 30:
            rows.append({"k": "rsi", "p": 3, "v": round(r, 1), "role": "main"})
        elif r >= 70:
            rows.append({"k": "rsi", "p": -3, "v": round(r, 1), "role": "main"})
        else:
            rows.append({"k": "rsi", "p": 0, "v": round(r, 1), "role": "main"})
    bb = boll(c, i)
    if bb:
        pos = (price - bb[0]) / (bb[2] - bb[0]) * 100 if bb[2] > bb[0] else 50
        p = 2 if price <= bb[0] else (-2 if price >= bb[2] else 0)
        rows.append({"k": "bb", "p": p, "v": round(pos), "lo": bb[0], "mid": bb[1], "up": bb[2], "role": "main"})
    if i >= 24:
        s5, s25 = sma_exact(c, i, 5), sma_exact(c, i, 25)
        rows.append({"k": "ma", "p": 1 if s5 > s25 else -1, "role": "sub"})
        m = mc[i]
        if m:
            rows.append({"k": "macd", "p": 1 if m[0] > m[1] else -1, "role": "sub"})
        rows.append({"k": "ma25", "p": 0, "v": round((price - s25) / s25 * 100, 2), "role": "ref"})
    else:
        m = mc[i]
        if m:
            rows.append({"k": "macd", "p": 1 if m[0] > m[1] else -1, "role": "sub"})
    return rows


def direction(s, gate=ENTRY_GATE):
    if s is None:
        return 0
    return 1 if s >= gate else (-1 if s <= -gate else 0)


def signal_day(sc, i, gate=ENTRY_GATE):
    """i 日目のサインが点灯何日目か（1＝初日、最大 10）。旧 JS の signalDay と同じ"""
    d = direction(sc[i], gate)
    if d == 0:
        return 0
    k = 0
    while k < 9 and i - k > 80:
        if direction(sc[i - 1 - k], gate) == d:
            k += 1
        else:
            break
    return k + 1


# ---------------- ATR・バックテスト ----------------
def atr_at(h, l, c, i, n=14):
    """i 日目時点の ATR（直近 n 本の真の値幅の単純平均）。JS の atr(bars.slice(0,i+1)) と同じ"""
    if i < n:
        return None
    s = 0.0
    for k in range(i - n + 1, i + 1):
        s += max(h[k] - l[k], abs(h[k] - c[k - 1]), abs(l[k] - c[k - 1]))
    return s / n


def backtest(o, h, l, c, sc=None, gate=ENTRY_GATE, sl_atr=SL_ATR, tp_atr=TP_ATR,
             max_hold=MAX_HOLD, fresh=FRESH_ONLY, start=0, cost=0.0, t=None):
    """旧 JS の backtest() と同じ規則。
    start … この位置より前は指標の助走だけに使う（JS の bars.slice(split) と同じにしたい時は
            系列ごと切って渡す。ここでは「助走は全部使い、取引は start 以降」にも使える）
    cost  … 1 回の往復コスト（価格の比率。例 0.8pip/150円=0.0000533）
    戻り値: 取引のリスト {i:入った日, j:出た日, dir, win, ret(%), how}"""
    n = len(c)
    if sc is None:
        sc = score_series(c)
    trades = []
    next_free = max(WARMUP, start)
    for i in range(WARMUP, n - 1):
        if i < next_free:
            continue
        d = direction(sc[i], gate)
        if d == 0:
            continue
        ps = sc[i - 1] if i - 1 >= WARMUP else None
        if fresh and ps is not None and direction(ps, gate) == d:
            continue
        a = atr_at(h, l, c, i)
        if not a:
            continue
        entry = c[i]
        slp, tpp = entry - d * sl_atr * a, entry + d * tp_atr * a
        out, held_to = None, i + 1
        last = n if max_hold is None else min(i + 1 + max_hold, n)
        for j in range(i + 1, last):
            held_to = j
            hit_sl = l[j] <= slp if d == 1 else h[j] >= slp
            hit_tp = h[j] >= tpp if d == 1 else l[j] <= tpp
            if hit_sl:
                out = ("loss", slp, "sl")
                break
            if hit_tp:
                out = ("win", tpp, "tp")
                break
        if out is None:
            if max_hold is None and held_to == n - 1:
                # 期限なしでまだ決着していない取引は数えない（結果が分からない）
                break
            ex = c[held_to]
            out = ("win" if (ex - entry) * d > 0 else "loss", ex, "time")
        ret = (out[1] - entry) / entry * 100 * d - cost * 100
        trades.append({"i": i, "j": held_to, "dir": d, "win": ret > 0 if cost else out[0] == "win",
                       "ret": ret, "how": out[2], "entry": entry, "exit": out[1]})
        next_free = held_to + 1
    return trades


def stats(trades, d=None):
    ts = [x for x in trades if d is None or x["dir"] == d]
    if not ts:
        return None
    n = len(ts)
    wins = [x["ret"] for x in ts if x["win"]]
    losses = [x["ret"] for x in ts if not x["win"]]
    gw, gl = sum(wins), -sum(losses)
    return {"n": n, "wr": len(wins) / n * 100, "exp": sum(x["ret"] for x in ts) / n,
            "pf": (gw / gl) if gl > 0 else float("inf"),
            "avgWin": (gw / len(wins)) if wins else 0.0,
            "avgLoss": (-gl / len(losses)) if losses else 0.0}
