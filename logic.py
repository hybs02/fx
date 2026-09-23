# -*- coding: utf-8 -*-
"""FX シグナルの計算本体（2026-09-23〜）。

build.py（GitHub Actions が1時間ごとに走らせる）と research/ の検証スクリプトが同じここを使う。
スマホの画面（index.html）は計算しない。data.json を表示するだけ。

■ 規則（22 年・11 ペア・スプレッド込みで検証して決めた。README と research/ を参照）
  RSI(14) が 25 以下に「入った最初」→ 買い／75 以上に「入った最初」→ 売り。
  損切りは入った値から ATR(14)×3 の逆指値。利確は置かない。5 本後（≒1週間後）に手仕舞う。1 ペア 1 ポジション。
  アプリは判定の時刻を固定しない：1時間ごとに『その時刻で締めた日足』で判定する（下の「時刻に縛られない版」）。
  下の 22 年の数字は「毎朝 9 時締めの日足」で測ったもの。
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
HOLD = 5               # 5 本後（日足なら 5 営業日後、1時間ごとの版なら約1週間後の同じ時刻）に手仕舞う
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


# ---------------- 時刻に縛られない版（2026-09-23〜 アプリはこちら） ----------------
# 1時間ごとに「その時刻で締めた日足（24時間ごとの値）」で RSI を計算し、しきい値を越えた最初の時刻をサインにする。
# 判定の時刻を固定しないので、いつ開いても最新。検証（research/study_cut.py）:
#   2024年7月〜（1時間足は約2年分しか取れない）で 86回・勝率64%・PF1.92（DMM の取引時間だけ・出口は入った1週間後）。
#   入るのが遅れると 2時間後 PF1.89／3時間後 1.74／6時間後 1.64／8時間後 1.49／12時間後 1.42／24時間後 1.00
#   → 3時間以内が目安、8時間を過ぎたら見送り（GitHub の定時実行は数時間遅れることがあるので、6時間より余裕を持たせた）。
#   22年（日足・終値だけの近似）でも、判定時刻を朝9時・欧州の昼・NYの昼にしてどれも通算で勝ち越し（1.51/1.23/1.21）。
ENTRY_BEST_H = 3
ENTRY_LIMIT_H = 8
MAX_SAME_SIDE = 2      # 同じ通貨に同じ向きで持つのは 2 つまで（research/study_portfolio.py）
ROLL_WARMUP = 150


def phase_series(t, h, l, c):
    """1時間足（t は足の始まりの時刻）から、UTC の各時刻（0〜23時）で締めた日足を作る。
    要素 = その時刻の終値、高値・安値は同じ時刻の1つ前の要素からの間。週に約5本ずつ。"""
    end = {x + 3600: i for i, x in enumerate(t)}
    out = {}
    for hh in range(24):
        ts = sorted(x for x in end if (x // 3600) % 24 == hh)
        C, H, L, prev = [], [], [], None
        for x in ts:
            i = end[x]
            lo = i if prev is None else end[prev] + 1
            C.append(c[i]); H.append(max(h[lo:i + 1])); L.append(min(l[lo:i + 1]))
            prev = x
        out[hh] = {"t": ts, "C": C, "H": H, "L": L}
    return out


def rolling_state(phases):
    """各時刻の RSI・ATR・Wilder の平均上昇/下落幅（その時刻締めの日足で）"""
    st = {}
    for hh, s in phases.items():
        r, ag, al = rsi_state(s["C"])
        for k, x in enumerate(s["t"]):
            if k >= ROLL_WARMUP:
                st[x] = {"rsi": r[k], "ag": ag[k], "al": al[k], "atr": atr_at(s["H"], s["L"], s["C"], k),
                         "c": s["C"][k], "hh": hh, "k": k}
    return st


def rolling_events(st, buy_at=BUY_AT, sell_at=SELL_AT):
    """しきい値を越えた時刻の一覧。同じ向きの越えが 5 日以内にあった時は同じ山（fresh=False）"""
    times = sorted(st)
    ev, last = [], {1: -1e18, -1: -1e18}
    for a, b in zip(times, times[1:]):
        if b - a > 3 * 3600:                 # 週末をまたぐ
            continue
        ra, rb = st[a]["rsi"], st[b]["rsi"]
        d = 1 if rb <= buy_at < ra else (-1 if rb >= sell_at > ra else 0)
        if not d:
            continue
        ev.append({"t": b, "dir": d, "from": ra, "to": rb, "fresh": b - last[d] > 5 * 86400})
        last[d] = b
    return ev


def dmm_open(t):
    """DMM FX で取引できる時刻か（t は UTC 秒）。日本時間 月曜 7:00〜土曜 5:50（夏時間。冬時間は 6:50 まで）。
    冬時間の土曜 5:50〜6:50 も閉まっている扱いにする（安全側）。
    Yahoo の1時間足には DMM が閉まった後の足（土曜 6〜7 時）も入っているので、検証でもここで外す。"""
    import datetime as _dt
    j = _dt.datetime.fromtimestamp(t + 9 * 3600, _dt.timezone.utc)
    m = j.hour * 60 + j.minute
    wd = j.weekday()                      # 月=0 … 日=6
    if wd == 6:
        return False
    if wd == 5 and m >= 5 * 60 + 50:
        return False
    if wd == 0 and m < 7 * 60:
        return False
    return True


def exit_time(te):
    """入った時刻 te の1週間後。取引時間外（土曜の朝など）に当たる時は、その前で最後に取引できる時刻"""
    tx = te + 7 * 86400
    while not dmm_open(tx):
        tx -= 3600
    return tx


def rolling_backtest(hourly, phases, st, ev, cost=0.0, sl_atr=SL_ATR, hold=HOLD, delay=0):
    """サインの時刻（から delay 時間後）に入り、入った時刻の1週間後に出る。損切りは1時間足の高値・安値で判定。
    アプリの手順と同じ：DMM が閉まっている時刻のサインは入らない（次に開くのは締め切りの後）、
    手仕舞いの時刻が閉まっていれば、その前で最後に取引できる時刻に出る。1ペア1ポジション。
    まだ出口が来ていない取引は含めない。"""
    t, h, l, c = hourly["t"], hourly["h"], hourly["l"], hourly["c"]
    end = {x + 3600: i for i, x in enumerate(t)}
    last = max(end) if end else 0
    out, busy = [], 0
    for e in ev:
        b = e["t"]
        if not e["fresh"] or b < busy or not dmm_open(b):
            continue
        te = b + delay * 3600
        if te not in end or not dmm_open(te):
            continue
        tx = exit_time(te)
        while tx > te and tx not in end:       # 祝日などで足が無い時は、その前の足で出る
            tx -= 3600
        if tx <= te or te + 7 * 86400 > last:
            continue
        d, en = e["dir"], c[end[te]]
        stop = en - d * sl_atr * st[b]["atr"]
        ex, how = c[end[tx]], "time"
        for x in range(te + 3600, tx + 1, 3600):
            i = end.get(x)
            if i is None:
                continue
            if (l[i] <= stop) if d == 1 else (h[i] >= stop):
                ex, how, tx = stop, "sl", x
                break
        out.append({"t": b, "te": te, "tx": tx, "dir": d, "entry": en, "exit": ex, "how": how,
                    "ret": ((ex - en) * d - cost) / en * 100})
        busy = tx
    return out


def next_hour_triggers(st, tlast, buy_at=BUY_AT, sell_at=SELL_AT, n=RSI_N):
    """次の1時間の終値がいくら以下（以上）なら RSI がしきい値を越えるか。
    次の時刻の RSI は『その時刻で締めた日足』の続きなので、その系列の最後の要素（≒24時間前）の
    Wilder の平均上昇幅 AG・平均下落幅 AL・終値 C から逆算する（r = しきい値の上昇/下落の比）。
      下がる時 x: AG'=(n-1)AG/n, AL'=((n-1)AL+x)/n  → AG'/AL' ≤ r ⇔ x ≥ (n-1)(AG/r − AL)
      上がる時 u: AG'=((n-1)AG+u)/n, AL'=(n-1)AL/n  → AG'/AL' ≤ r ⇔ u ≤ (n-1)(r·AL − AG)
    24時間前の時点ですでにしきい値の外にいる（AG/AL ≤ r）時は、少し上がっても外のままなので『上がる時』の式になる。
    （以前は常に下がる時の式を使っていて、その場合に現在値より上に「この値以下なら買い」が出ていた）"""
    now = st[tlast]["rsi"]
    nxt = ((tlast + 3600) // 3600) % 24
    prev = [x for x in st if (x // 3600) % 24 == nxt and x <= tlast]
    if not prev:
        return None, None
    q = st[max(prev)]
    ag, al, c = q["ag"], q["al"], q["c"]
    if ag is None or al is None:
        return None, None
    r, R = buy_at / (100 - buy_at), sell_at / (100 - sell_at)
    buy = sell = None
    if now > buy_at:                      # 今が 25 より上なら、次の1時間で 25 以下に入れば『入った最初』
        buy = c - (n - 1) * (ag / r - al) if ag >= r * al else c + (n - 1) * (r * al - ag)
    if now < sell_at:
        sell = c + (n - 1) * (R * al - ag) if ag <= R * al else c - (n - 1) * (ag / R - al)
    return buy, sell


def exposure(pair, d):
    """通貨ごとの向き（+1 買い持ち / -1 売り持ち）。例 EURJPY の買い → EUR +1, JPY -1"""
    return {pair[:3]: d, pair[3:]: -d}


def portfolio(trades, cap=MAX_SAME_SIDE):
    """資金に対する増え方と最大の落ち込み（1回のリスク＝資金の1%あたり・単利）。
    trades: {pair, dir, t0, t1, R}（R＝損益÷損切り幅）。同じ通貨に同じ向きで cap 本を持っている時の新しいサインは見送る。
    サインは同じ日に固まって出る（22年で半分以上が、同じ通貨・同じ向きの取引を持っている最中に出た）ので、
    1回あたりのリスクだけでなく、同時に持つ本数を抑えないと資金の落ち込みが大きくなる。"""
    trades = sorted(trades, key=lambda x: x["t0"])
    open_, eq, peak, mdd, taken = [], 0.0, 0.0, 0.0, 0
    def close_until(t):
        nonlocal eq, peak, mdd
        for o in sorted([o for o in open_ if o["t1"] <= t], key=lambda o: o["t1"]):
            open_.remove(o)
            eq += o["R"]; peak = max(peak, eq); mdd = min(mdd, eq - peak)
    for x in trades:
        close_until(x["t0"])
        ex = exposure(x["pair"], x["dir"])
        if cap and any(sum(1 for o in open_ if exposure(o["pair"], o["dir"]).get(c) == s) >= cap for c, s in ex.items()):
            continue
        open_.append(x); taken += 1
    close_until(float("inf"))
    return {"n": taken, "total": round(eq, 1), "mdd": round(mdd, 1)}


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
