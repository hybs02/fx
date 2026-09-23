# -*- coding: utf-8 -*-
"""FX シグナルの計算本体（2026-09-23〜）。

build.py（GitHub Actions が毎朝走らせる）と research/ の検証スクリプトが同じここを使う。
スマホの画面（index.html）は計算しない。data.json を表示するだけ。

■ 規則（22 年・11 ペア・スプレッド込みで検証して決めた。README と research/ を参照）
  毎朝 9 時（UTC 0 時）の値で RSI(14) を計算し、
    25 以下に「入った初日」→ 買い／75 以上に「入った初日」→ 売り
  その日の昼 12 時までに入る。損切りは入った値から ATR(14)×3 の逆指値。利確は置かない。
  5 営業日後の朝（9〜12 時）に手仕舞う。1 ペア 1 ポジション。
  成績（2004〜2026・11 ペア合算）：564 回・勝率 52%・1 回平均 +0.22%・PF1.34、
  2004-10 / 11-14 / 15-18 / 19-21 / 直近 5 年 のどの時代も PF1.16 以上。

■ 日足の作り方（重要）
  Yahoo の為替日足は 2010 年 6 月ごろから「終値＝その日（ロンドン日付）の UTC 0 時の値」で、
  高値・安値はその日 1 日ぶん。つまり終値はその日の『始まり』の値。これを
  「東京 9 時締めの日足」に並べ直してから使う（make_bars）。以前（〜2026-09-08）の検証は
  並べ直していなかったため、入った日の値動きを飛ばし、その日の値幅を先読みしていた。
"""
import math

RSI_N = 14
BUY_AT = 25            # RSI がこの値以下に入った初日に買い
SELL_AT = 75           # RSI がこの値以上に入った初日に売り
SL_ATR = 3.0           # 損切り＝入った値から ATR×3
HOLD = 5               # 5 営業日後の朝に手仕舞う
ENTRY_DEADLINE = 12    # 入るのは 9 時〜この時刻まで（それより遅いと成績が落ちる：research/study_delay.py）
WARMUP = 250


# ---------------- 日足の並べ直し ----------------
def snapshot_start(o, h, l, c):
    """Yahoo 日足が「始値≒終値＝UTC 0 時の値」形式に切り替わった位置（それより前は普通の日足）"""
    r = [abs(a - d) / (b - e) if b > e else 0.0 for a, b, e, d in zip(o, h, l, c)]
    for i in range(60, len(r)):
        w = sorted(r[i - 60:i])
        if (w[29] + w[30]) / 2 < 0.1:
            return i - 60
    return 0


def make_bars(dates, o, h, l, c):
    """東京 9 時締めの日足: C[i]=c[i]（i 日 9 時の値）、H[i]=max(h[i-1],C[i])、L[i]=min(l[i-1],C[i])。
    切り替わり前（〜2010年）は普通の日足なのでそのまま。"""
    s = snapshot_start(o, h, l, c)
    out = {"date": [], "C": [], "H": [], "L": []}
    for i in range(len(c)):
        if s and i == s:
            continue
        if i > s:
            H, L = max(h[i - 1], c[i]), min(l[i - 1], c[i])
        else:
            H, L = h[i], l[i]
        out["date"].append(dates[i]); out["C"].append(c[i]); out["H"].append(H); out["L"].append(L)
    return out


# ---------------- 指標 ----------------
def rsi_state(c, n=RSI_N):
    """各日の RSI と、Wilder の平均上昇幅・平均下落幅（翌朝のサイン価格を逆算するのに使う）"""
    rsi, ag_s, al_s = [None] * len(c), [None] * len(c), [None] * len(c)
    if len(c) < n + 1:
        return rsi, ag_s, al_s
    ag = al = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]
        ag += max(d, 0.0); al += max(-d, 0.0)
    ag /= n; al /= n
    for i in range(n, len(c)):
        if i > n:
            d = c[i] - c[i - 1]
            ag = (ag * (n - 1) + max(d, 0.0)) / n
            al = (al * (n - 1) + max(-d, 0.0)) / n
        rsi[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
        ag_s[i], al_s[i] = ag, al
    return rsi, ag_s, al_s


def rsi_series(c, n=RSI_N):
    return rsi_state(c, n)[0]


def atr_at(H, L, C, i, n=14):
    if i < n:
        return None
    s = 0.0
    for k in range(i - n + 1, i + 1):
        s += max(H[k] - L[k], abs(H[k] - C[k - 1]), abs(L[k] - C[k - 1]))
    return s / n


def sma_series(c, n):
    out, s = [None] * len(c), 0.0
    for i, v in enumerate(c):
        s += v
        if i >= n:
            s -= c[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema_series(a, n):
    out = [None] * len(a)
    if len(a) < n:
        return out
    k = 2 / (n + 1)
    v = sum(a[:n]) / n
    out[n - 1] = v
    for i in range(n, len(a)):
        v = a[i] * k + v * (1 - k)
        out[i] = v
    return out


def boll_at(c, i, n=20, k=2):
    if i + 1 < n:
        return None
    w = c[i - n + 1:i + 1]
    m = sum(w) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in w) / n)
    return m - k * sd, m, m + k * sd


def macd_at(c):
    """最後の時点の (MACD, シグナル)"""
    e12, e26 = ema_series(c, 12), ema_series(c, 26)
    m = [a - b if a is not None and b is not None else None for a, b in zip(e12, e26)]
    mm = [x for x in m if x is not None]
    if len(mm) < 9:
        return None
    sig = ema_series(mm, 9)[-1]
    return mm[-1], sig


# ---------------- サイン ----------------
def signals(C, buy_at=BUY_AT, sell_at=SELL_AT, n=RSI_N):
    """各日の向き（+1 買い / -1 売り / 0）。しきい値を『越えた初日』だけ"""
    r = rsi_series(C, n)
    s = [0] * len(C)
    for i in range(1, len(C)):
        a, b = r[i - 1], r[i]
        if a is None or b is None:
            continue
        if b <= buy_at < a:
            s[i] = 1
        elif b >= sell_at > a:
            s[i] = -1
    return s, r


def trigger_prices(C, ag, al, i, buy_at=BUY_AT, sell_at=SELL_AT, n=RSI_N):
    """次の朝 9 時の値がいくら以下（以上）なら RSI がしきい値を越えるか。
    Wilder 平滑: 次の変化を x とすると AG'=(AG*(n-1)+上昇)/n, AL'=(AL*(n-1)+下落)/n。
      買い（RSI≦buy_at）: 下落 x ≧ (n-1)(AG/r - AL)  r=buy_at/(100-buy_at)
      売り（RSI≧sell_at）: 上昇 x ≧ (n-1)(R·AL - AG)  R=sell_at/(100-sell_at)
    今日すでにしきい値の外にいる時は、明日『入った初日』にはならないので None。"""
    rs = 100 - 100 / (1 + ag[i] / al[i]) if al[i] else 100.0
    r, R = buy_at / (100 - buy_at), sell_at / (100 - sell_at)
    buy = sell = None
    if rs > buy_at:
        buy = C[i] - (n - 1) * (ag[i] / r - al[i])
    if rs < sell_at:
        sell = C[i] + (n - 1) * (R * al[i] - ag[i])
    return buy, sell


# ---------------- バックテスト ----------------
def backtest(bars, sig, sl_atr=SL_ATR, hold=HOLD, cost=0.0, start=WARMUP):
    """sig[i] の向きで i 日 9 時に入り、損切り（ATR×sl_atr）か hold 本後の 9 時で出る。
    損切りの判定は各日の高値・安値（同じ日に両方届く心配は無い：利確を置かないため）。
    cost … 往復コスト（価格単位。スプレッド 1 回ぶん）
    まだ手仕舞い日が来ていない取引は含めない（結果が分からないので）。"""
    H, L, C = bars["H"], bars["L"], bars["C"]
    n, out, nf = len(C), [], start
    for i in range(start, n):
        if i < nf or not sig[i]:
            continue
        if i + hold >= n:
            break
        d = sig[i]
        a = atr_at(H, L, C, i)
        if not a:
            continue
        e = C[i]
        stop = e - d * sl_atr * a
        ex, how, j = None, "time", i + hold
        for k in range(i + 1, i + hold + 1):
            if (L[k] <= stop) if d == 1 else (H[k] >= stop):
                ex, how, j = stop, "sl", k
                break
        if ex is None:
            ex = C[i + hold]
        out.append({"i": i, "j": j, "dir": d, "entry": e, "exit": ex, "how": how, "atr": a,
                    "ret": ((ex - e) * d - cost) / e * 100})
        nf = j + 1
    return out


def stats(trades):
    if not trades:
        return None
    r = [t["ret"] for t in trades]
    g = sum(x for x in r if x > 0)
    lo = -sum(x for x in r if x < 0)
    w = sum(1 for x in r if x > 0)
    return {"n": len(r), "wr": round(w / len(r) * 100, 1), "exp": round(sum(r) / len(r), 3),
            "pf": round(g / lo, 2) if lo > 0 else None,
            "avgWin": round(g / w, 3) if w else 0, "avgLoss": round(-lo / (len(r) - w), 3) if len(r) > w else 0,
            "sl": round(sum(1 for t in trades if t["how"] == "sl") / len(r) * 100, 1)}
