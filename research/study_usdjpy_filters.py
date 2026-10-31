# -*- coding: utf-8 -*-
"""ドル円だけの材料で、いまの規則（RSI30/70・ATR×4・1週間）をもっと良くできるかを調べる。

試すもの:
  ・RSI の日数（7〜21日）としきい値
  ・出口（1週間で出る／RSI が50に戻ったら出る）
  ・ドル円に効きそうな外の材料で絞る：米10年・5年金利の動き、恐怖指数（VIX）、日経平均・S&P500の動き、
    ドル指数（DXY）との差（円だけが動いたのか、ドル全体が動いたのか）
選び方は study_usdjpy.py と同じ（のぞき見を防ぐ）:
  設計期間 2004〜2018 の 3 つの時代それぞれの PF の最小値で選び、選ぶのに使っていない 2019〜 で確かめる。
外の材料は「入る時刻（東京9時）より前に引けた値」だけを使う。
python research/fetch.py USDJPY のあと、外の材料は yahoo_TNX/FVX/VIX/N225/GSPC/DXY.json をキャッシュに置く。"""
import sys, io, os, json, bisect, datetime as dt
from common import load_bars, load_irx, SPREAD, pip, logic, HERE

sys.stdout.reconfigure(encoding="utf-8")
P = "USDJPY"
COST = SPREAD[P] * pip(P)
ERAS = [("2004", "2011"), ("2011", "2015"), ("2015", "2019"), ("2019", "2021-09"), ("2021-09", "2100")]
SPLIT = "2019"
b = load_bars(P)
D = [x.isoformat() for x in b["date"]]
irx = load_irx()


def ext(name):
    d = json.load(io.open(os.path.join(HERE, "cache", f"yahoo_{name}.json")))
    return d["t"], d["c"]


X = {k: ext(k) for k in ("TNX", "FVX", "VIX", "N225", "GSPC", "DXY")}


def ts(i):
    return dt.datetime.combine(b["date"][i], dt.time(), dt.timezone.utc).timestamp()


def asof(name, t, back=0):
    """t（東京9時）より1時間以上前に始まった足のうち、back 本前の終値"""
    T, C = X[name]
    k = bisect.bisect_left(T, t - 3600) - 1 - back
    return C[k] if k >= 0 else None


def chg(name, i, n):
    a, z = asof(name, ts(i), n), asof(name, ts(i))
    return None if a is None or z is None else z - a


def rchg(name, i, n):
    a, z = asof(name, ts(i), n), asof(name, ts(i))
    return None if not a or z is None else (z / a - 1) * 100


def with_swap(tr):
    for t in tr:
        t["ret"] += logic.swap_pct(irx, ts(t["i"]), ts(t["j"]), t["dir"])
    return tr


def run(lo=30, hi=70, sl=4.0, hold=5, n=14):
    s, r = logic.signals(b["C"], lo, hi, n)
    return with_swap(logic.backtest(b, s, sl_atr=sl, hold=hold, cost=COST)), s, r


def run_exit50(lo=30, hi=70, sl=4.0, maxhold=10, n=14):
    """RSI が50に戻った日の9時で出る（最長 maxhold 日・損切りは同じ）"""
    s, r = logic.signals(b["C"], lo, hi, n)
    H, L, C = b["H"], b["L"], b["C"]
    out, nf = [], logic.WARMUP
    for i in range(logic.WARMUP, len(C)):
        if i < nf or not s[i]:
            continue
        if i + maxhold >= len(C):
            break
        d, a = s[i], logic.atr_at(H, L, C, i)
        e, stop = C[i], C[i] - d * sl * a
        ex, how, j = None, "time", i + maxhold
        for k in range(i + 1, i + maxhold + 1):
            if (L[k] <= stop) if d == 1 else (H[k] >= stop):
                ex, how, j = stop, "sl", k
                break
            if (r[k] >= 50) if d == 1 else (r[k] <= 50):
                ex, how, j = C[k], "rsi", k
                break
        if ex is None:
            ex = C[j]
        out.append({"i": i, "j": j, "dir": d, "entry": e, "exit": ex, "how": how, "atr": a,
                    "ret": ((ex - e) * d - COST) / e * 100})
        nf = j + 1
    return with_swap(out)


def pf(tr):
    g = sum(t["ret"] for t in tr if t["ret"] > 0); l = -sum(t["ret"] for t in tr if t["ret"] < 0)
    return g / l if l > 0 else 9.99


def era(tr, a, z):
    return [t for t in tr if a <= D[t["i"]] < z]


def score(tr):
    dsg = [t for t in tr if D[t["i"]] < SPLIT]; tst = [t for t in tr if D[t["i"]] >= SPLIT]
    return {"worst": min(pf(era(tr, a, z)) for a, z in ERAS[:3]), "nd": len(dsg), "pfd": pf(dsg),
            "nt": len(tst), "pft": pf(tst), "expt": sum(t["ret"] for t in tst) / max(1, len(tst)),
            "eras": [pf(era(tr, a, z)) for a, z in ERAS]}


def show(name, s):
    print(f"{name:44s} 設計 最悪{s['worst']:4.2f} PF{s['pfd']:4.2f}({s['nd']:3d}) | 確かめ PF{s['pft']:4.2f}({s['nt']:2d}) 平均{s['expt']:+.2f}% | "
          + " ".join(f"{x:4.2f}" for x in s["eras"]))


base, sig, rsi = run()
print("時代: 2004-10 2011-14 2015-18 | 2019-21 2021-")
show("いまの規則 RSI14 30/70 ATR×4 1週間", score(base))

print("\n== RSI の日数としきい値（設計期間の取引40回以上） ==")
rows = []
for n in (7, 9, 10, 14, 21):
    for lo in (15, 20, 25, 30, 35):
        tr, _, _ = run(lo, 100 - lo, 4.0, 5, n)
        s = score(tr)
        if s["nd"] >= 40:
            rows.append((s["worst"], f"RSI{n} {lo}/{100-lo}", s))
for w, name, s in sorted(rows, key=lambda x: -x[0])[:8]:
    show(name, s)

print("\n== 出口：RSI が50に戻ったら出る ==")
for mh in (5, 7, 10):
    show(f"RSI50で出る 最長{mh}日", score(run_exit50(maxhold=mh)))

print("\n== 外の材料で絞る（いまの規則の取引のうち、条件に合うものだけ） ==")
FEAT = {}
for t in base:
    i = t["i"]
    FEAT[i] = {
        "tnx5": chg("TNX", i, 5), "tnx20": chg("TNX", i, 20), "fvx5": chg("FVX", i, 5), "fvx20": chg("FVX", i, 20),
        "vix": asof("VIX", ts(i)), "vix5": chg("VIX", i, 5),
        "nk5": rchg("N225", i, 5), "nk20": rchg("N225", i, 20), "sp5": rchg("GSPC", i, 5), "sp20": rchg("GSPC", i, 20),
        "dxy5": rchg("DXY", i, 5), "dxy20": rchg("DXY", i, 20),
        "uj5": (b["C"][i] / b["C"][i - 5] - 1) * 100, "uj20": (b["C"][i] / b["C"][i - 20] - 1) * 100,
    }


def keep(cond):
    out = []
    for t in base:
        f = FEAT[t["i"]]
        try:
            if cond(f, t["dir"]):
                out.append(t)
        except TypeError:     # 材料が無い日（古すぎる等）はそのまま入る
            out.append(t)
    return out


cands = []
for k in ("tnx5", "tnx20", "fvx5", "fvx20", "nk5", "nk20", "sp5", "sp20", "dxy5", "dxy20"):
    cands.append((f"{k} が取引の向きと同じ", lambda f, d, k=k: f[k] * d >= 0))
    cands.append((f"{k} が取引の向きと逆", lambda f, d, k=k: f[k] * d <= 0))
for v in (20, 25, 30, 35):
    cands.append((f"VIX {v} 以上では買わない", lambda f, d, v=v: not (d == 1 and f["vix"] >= v)))
    cands.append((f"VIX {v} 以上では入らない", lambda f, d, v=v: f["vix"] < v))
cands.append(("VIX が5日で上がっていたら買わない", lambda f, d: not (d == 1 and f["vix5"] > 0)))
for n in (5, 20):
    # 円だけが動いた（ドル指数は動いていない）＝ドル円の動きからドル全体の動きを引いた分
    cands.append((f"円だけの動き{n}日が取引の向きと逆", lambda f, d, n=n: (f[f"uj{n}"] - f[f"dxy{n}"]) * d <= 0))
    cands.append((f"ドル全体の動き{n}日が取引の向きと逆", lambda f, d, n=n: f[f"dxy{n}"] * d <= 0))
res = []
for name, c in cands:
    tr = keep(c)
    s = score(tr)
    if s["nd"] >= 30:
        res.append((s["worst"], name, s))
res.sort(key=lambda x: -x[0])
print("設計期間の最悪時代 PF の高い順（設計の取引30回以上）")
for w, name, s in res[:12]:
    show(name, s)
print("…下位")
for w, name, s in res[-4:]:
    show(name, s)
print(f"\n候補 {len(res)} 通りのうち、設計の最悪時代 PF がいまの規則（{score(base)['worst']:.2f}）より上:",
      sum(1 for w, _, _ in res if w > score(base)["worst"]))
print("そのうち 2019 年以降の PF もいまの規則より上:",
      [name for w, name, s in res if w > score(base)["worst"] and s["pft"] > score(base)["pft"]])


print("\n== 採った絞り込み：円だけの動き（logic.yen_ok）。サインの段階で外す（外した日は次のサインを待つ） ==")
DXD = {"t": X["DXY"][0], "c": X["DXY"][1]}


def yen_at(i, n=logic.YEN_N):
    return logic.yen_move(b["C"][i], b["C"][i - n], logic.asof(DXD, ts(i)), logic.asof(DXD, ts(i - n)))


def run_yen(n=logic.YEN_N, lo=30, sl=4.0, hold=5):
    s, _ = logic.signals(b["C"], lo, 100 - lo)
    s = [x if not x or logic.yen_ok(x, yen_at(i, n)) else 0 for i, x in enumerate(s)]
    return with_swap(logic.backtest(b, s, sl_atr=sl, hold=hold, cost=COST))


show("いまの規則", score(base))
for n in (3, 4, 5, 7, 10):
    show(f"円だけの動き {n}日", score(run_yen(n)))
pick = run_yen()
for nm, tr in (("  買いだけ", [t for t in pick if t["dir"] == 1]), ("  売りだけ", [t for t in pick if t["dir"] == -1])):
    show(nm, score(tr))
print("RSI 30/70 の周り（損切り×・日数）で、絞り込みあり／なしの 2019 年以降の PF:")
for lo in (25, 30, 35):
    for sl in (3.0, 4.0):
        for hold in (3, 5, 7):
            a, _, _ = run(lo, 100 - lo, sl, hold)
            z = run_yen(lo=lo, sl=sl, hold=hold)
            sa, sz = score(a), score(z)
            print(f"  RSI{lo}/{100-lo} ×{sl:.0f} {hold}日: 最悪 {sa['worst']:.2f}→{sz['worst']:.2f}  確かめ {sa['pft']:.2f}→{sz['pft']:.2f}")

print("\n== 1時間ごとの判定（直近約2年・アプリと同じ形） ==")
from common import load_hourly
h = load_hourly(P)
dxh = json.load(io.open(os.path.join(HERE, "cache", "yahoo_h_DXY.json")))
ph = logic.phase_series(h["t"], h["h"], h["l"], h["c"])
st = logic.rolling_state(ph)
ev = logic.rolling_events(st)


def ev_yen(e):
    s = ph[st[e["t"]]["hh"]]; k = st[e["t"]]["k"]; n = logic.YEN_N
    return logic.yen_move(s["C"][k], s["C"][k - n], logic.asof(dxh, e["t"]), logic.asof(dxh, s["t"][k - n]))


for nm, evs in (("絞り込みなし", ev), ("円だけの動きで絞る", [e for e in ev if logic.yen_ok(e["dir"], ev_yen(e))])):
    rb = logic.rolling_backtest(h, ph, st, evs, cost=COST)
    for t in rb:
        t["ret"] += logic.swap_pct(irx, t["te"], t["tx"], t["dir"])
    s = logic.stats(rb)
    print(f"  {nm}: n={s['n']} 勝率{s['wr']}% 平均{s['exp']:+.3f}% PF{pf(rb):.2f}")
print("  外れたサイン:", [(dt.datetime.fromtimestamp(e["t"] + 9 * 3600, dt.timezone.utc).strftime("%Y-%m-%d %H時"), e["dir"], round(ev_yen(e), 2))
                       for e in ev if e["fresh"] and logic.dmm_open(e["t"]) and not logic.yen_ok(e["dir"], ev_yen(e))])
