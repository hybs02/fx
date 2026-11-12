"""ドル円シグナルの自動計算（GitHub Actions の update-signals）を、この PC から1時間ごとに起動する。

GitHub の定時実行は実際には3〜7時間おきにしか動かないため、タスクスケジューラが毎時5分に pythonw で呼ぶ。
DMM FX が閉まっている間（土曜6時〜月曜6時）は何もしない。結果は同じフォルダの kick.log に1行ずつ書く。
vbs にはしない（窓を隠して別のプログラムを起こす vbs は Defender に検疫されることがある）。
"""

from __future__ import annotations

import subprocess
import time
from datetime import datetime
from pathlib import Path

GH = r"C:\Program Files\GitHub CLI\gh.exe"
LOG = Path(__file__).resolve().parent / "kick.log"
NO_WINDOW = 0x08000000          # gh は端末のプログラム。これが無いと黒い窓が一瞬出る


def closed(now: datetime) -> bool:
    """DMM FX が閉まっている時間帯か（土曜6時〜月曜6時）。"""
    day, hour = now.weekday(), now.hour          # 0=月 … 5=土, 6=日
    return day == 6 or (day == 5 and hour >= 6) or (day == 0 and hour < 6)


def main() -> int:
    if closed(datetime.now()):
        return 0
    try:
        code = subprocess.run(
            [GH, "workflow", "run", "update-signals", "-R", "hybs02/fx"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW, timeout=120).returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        code = type(exc).__name__
    with LOG.open("a", encoding="utf-8") as out:
        out.write("%s gh=%s\n" % (time.strftime("%Y/%m/%d %H:%M:%S"), code))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
