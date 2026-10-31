"""使い方の画像（guide/*.webp）を撮る。python tools/shoot_guide.py
決めた状態（時刻・データ・記録）の画面を、Chrome でスマホ幅（375px）に撮る。
index.html の前に、時刻・fetch・localStorage を差し替える小さなスクリプトを差し込んだ写しを作り、
幅375pxの iframe に入れてヘッドレス Chrome で撮る（ヘッドレスは幅500px未満にできないため）。
値は説明用の例。data.json（python build.py で作る）と fundamentals.json を土台にする。"""
import json, subprocess, copy, tempfile
import datetime as dt
from pathlib import Path
from PIL import Image

APP = Path(__file__).resolve().parent.parent
OUT = APP / "guide"
WORK = Path(tempfile.mkdtemp(prefix="shoot_guide_"))
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
W, H, DPR = 375, 812, 2

src = (APP / "index.html").read_text(encoding="utf-8")
base = json.loads((APP / "data.json").read_text(encoding="utf-8"))
fund = json.loads((APP / "fundamentals.json").read_text(encoding="utf-8"))

T = 1793766000           # 2026-11-04(水) 13:20 JST
SIG_T = T - 4800         # 12:00 JST
ATR = 0.841


def exit_time(te):
    """logic.exit_time と同じ（入った1週間後。DMM が閉まっている時刻なら、その前の取引できる時刻）"""
    t = te + 7 * 86400
    while True:
        d = dt.datetime.fromtimestamp(t + 9 * 3600, dt.timezone.utc)
        w, m = (d.weekday() + 1) % 7, d.hour * 60 + d.minute
        if not (w == 0 or (w == 6 and m >= 350) or (w == 1 and m < 420)):
            return t
        t -= 3600


def data_wait():
    d = copy.deepcopy(base)
    d["updatedTs"] = T - 900
    d["live"]["t"] = T - 900
    return d


def data_go():
    d = data_wait()
    p = 152.846
    d.update(price=p, rsi=29.6, rsiPrev=31.4, live={"p": p, "t": T - 900})
    d["trig"] = {"buy": None, "sell": 158.91}
    d["sig"] = {"dir": 1, "t": SIG_T, "from": 31.4, "to": 29.6, "price": p, "atr": ATR, "atrPips": 84.1, "exit": exit_time(SIG_T),
                "yenOk": True, "yen": {"move": -0.92, "uj": -1.63, "dxy": -0.71}}
    d["yen"] = {"move": -0.95, "uj": -1.66, "dxy": -0.71}
    return d


POS = [{"pair": "USDJPY", "dir": 1, "entry": 152.851, "stop": round(152.851 - 4 * ATR, 3), "lots": 1, "mini": False,
        "units": 10000, "t": T - 1200, "exitT": exit_time(T - 1200)}]
LS = {"fx_bal": 2000000, "fx_risk": 2}

SHOTS = [
    # 名前, データ, 記録, 表示後に動かす JS, 切り取る高さ（px）
    ("wait", data_wait(), [], "window.scrollTo(0,0)", 548),
    ("go", data_go(), [], "window.scrollTo(0,0)", 812),
    ("step1", data_go(), [], "document.querySelector('#o1 .steps').scrollIntoView()", 812),
    ("step2", data_go(), [], "document.querySelector('#o1 .steps h4').scrollIntoView()", 812),
    ("step3", data_go(), [], "document.querySelectorAll('#o1 .steps h4')[1].scrollIntoView()", 560),
    ("hold", data_go(), POS, "window.scrollTo(0,0)", 655),
]

PRE = """<script>
(function(){
  const T = %d;
  Date.now = () => T * 1000;
  try{ localStorage.clear(); }catch(e){}
  const LS = %s;
  for(const k in LS) localStorage.setItem(k, JSON.stringify(LS[k]));
  const D = %s, F = %s;
  window.fetch = async u => ({ok:true, status:200, json: async () => String(u).includes("fundamentals") ? F : D});
  addEventListener("load", () => setTimeout(() => { %s; }, 1500));
})();
</script>
"""

for name, data, pos, after, ch in SHOTS:
    ls = dict(LS, uj_pos=pos)
    html = src.replace("<script>\n\"use strict\";", PRE % (T, json.dumps(ls), json.dumps(data, ensure_ascii=False),
                                                           json.dumps(fund, ensure_ascii=False), after) + "<script>\n\"use strict\";", 1)
    assert html != src
    page = WORK / f"page_{name}.html"
    page.write_text(html, encoding="utf-8")
    wrap = WORK / f"wrap_{name}.html"
    wrap.write_text(f'<html><body style="margin:0;background:#0b0f17"><iframe src="{page.name}" style="width:{W}px;height:{H}px;border:0;display:block"></iframe></body></html>', encoding="utf-8")
    raw = WORK / f"raw_{name}.png"
    # 窓の下端は描かれないことがあるので、窓は撮る高さより大きくする
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--force-device-scale-factor={DPR}",
                    "--allow-file-access-from-files", f"--window-size=500,{H + 300}", "--virtual-time-budget=6000",
                    f"--screenshot={raw}", wrap.as_uri()], check=True, capture_output=True, timeout=60)
    im = Image.open(raw).convert("RGB").crop((0, 0, W * DPR, ch * DPR))
    OUT.mkdir(exist_ok=True)
    im.save(OUT / f"{name}.webp", quality=82, method=6)
    print(name, (OUT / f"{name}.webp").stat().st_size)
