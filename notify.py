# -*- coding: utf-8 -*-
"""新しいサインが出たら、登録したスマホに通知を送る（GitHub Actions が build.py のあとに実行）。

  ・送るのは、入ってよいサインだけ（円だけの動きで外れたもの・介入警戒で止まる買いは送らない）
  ・同じサインは1回だけ。送ったサインの時刻を data.json の notified に書き、次の回は前回の data.json から引き継ぐ
  ・鍵と宛先は GitHub の Secrets：VAPID_PRIVATE（通知の鍵）・PUSH_SUBS（アプリの設定タブで出る宛先。複数なら [ ] で並べる）
    どちらか無ければ送らない（計算は止めない）

使い方:  python notify.py [前回の data.json]   （無ければ prev.json）
         python notify.py --dry-run            （送らずに、送る内容だけ出す）
         python notify.py --test               （サインに関係なく試しの通知を送る。data.json は書き換えない）
"""
import datetime as dt, io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
JST = dt.timezone(dt.timedelta(hours=9))
SITE = "https://hybs02.github.io/fx/"     # 通知を押した時に開くページ
# 通知の送り主（VAPID の sub）。パスの無い https の URL か mailto: でないと受け付けられない
KEEP = 20                  # 送ったサインの時刻を何件まで覚えておくか


def read(path):
    try:
        return json.load(io.open(path, encoding="utf-8"))
    except Exception:
        return None


def hm(t):
    return dt.datetime.fromtimestamp(t, JST).strftime("%H:%M")


def message(d, fund):
    """送るなら (題, 本文)。送らないなら (None, 理由)"""
    s = d.get("sig")
    if not s:
        return None, "サインなし"
    if s.get("yenOk") is False:
        return None, "ドル全体の動きで外れたサイン"
    al = ((fund or {}).get("pairAlerts") or {}).get("USDJPY")
    p = (d.get("live") or {}).get("p") or d.get("price")
    if al and p is not None:
        if (al["dangerDir"] == "up" and s["dir"] == 1 and p >= al["level"] - al["near"]) or \
           (al["dangerDir"] == "down" and s["dir"] == -1 and p <= al["level"] + al["near"]):
            return None, "介入警戒で止まる向き"
    r = d["rule"]
    dn = "買い" if s["dir"] == 1 else "売り"
    return (f"ドル円 {dn}サイン",
            f"{hm(s['t'])} に RSI {s['to']}（{p:.3f}）。{r['best']}時間以内が目安・締め切り {hm(s['t'] + r['limit'] * 3600)}。アプリで手順を確かめて")


def send(subs, key, title, body):
    from pywebpush import webpush, WebPushException
    ok = 0
    for sub in subs:
        try:
            webpush(sub, json.dumps({"title": title, "body": body, "url": SITE}, ensure_ascii=False),
                    vapid_private_key=key, vapid_claims={"sub": "https://hybs02.github.io"}, ttl=8 * 3600, headers={"Urgency": "high"})
            ok += 1
        except WebPushException as e:
            code = e.response.status_code if e.response is not None else "?"
            # 404・410 はその端末の登録が消えている（アプリの設定タブで登録し直す）
            print(f"送れなかった宛先 {sub.get('endpoint', '')[:40]}…: {code}", flush=True)
    return ok


def main():
    dry = "--dry-run" in sys.argv
    if "--test" in sys.argv:
        key, subs = os.environ.get("VAPID_PRIVATE", "").strip(), os.environ.get("PUSH_SUBS", "").strip()
        if not key or not subs:
            raise SystemExit("通知の鍵か宛先が無い（GitHub の Secrets：VAPID_PRIVATE・PUSH_SUBS）")
        subs = json.loads(subs)
        subs = subs if isinstance(subs, list) else [subs]
        n = send(subs, key, "ドル円シグナル（試し）", "GitHub の自動計算から送った試しの通知です")
        print(f"試しの通知を送った（{n}/{len(subs)} 台）")
        return
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    d = read(os.path.join(HERE, "data.json"))
    prev = read(args[0] if args else os.path.join(HERE, "prev.json")) or {}
    fund = read(os.path.join(HERE, "fundamentals.json"))
    if not d:
        raise SystemExit("data.json が無い")
    done = list(prev.get("notified") or [])
    title, body = message(d, fund)
    s = d.get("sig")
    if title and s["t"] not in done:
        key, subs = os.environ.get("VAPID_PRIVATE", "").strip(), os.environ.get("PUSH_SUBS", "").strip()
        if dry:
            print("送る内容:", title, "／", body)
        elif not key or not subs:
            print("通知の鍵か宛先が無いので送らない（GitHub の Secrets：VAPID_PRIVATE・PUSH_SUBS）")
        else:
            subs = json.loads(subs)
            subs = subs if isinstance(subs, list) else [subs]
            n = send(subs, key, title, body)
            print(f"通知を送った：{title}（{n}/{len(subs)} 台）", flush=True)
            if n:
                done.append(s["t"])
    else:
        print("通知なし：" + (body if not title else "このサインは送り済み"))
    d["notified"] = done[-KEEP:]
    if not dry:
        io.open(os.path.join(HERE, "data.json"), "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
