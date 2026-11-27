"""과거 자료 한꺼번에 채우기(한 번만 손으로 돌리는 용도).

사용: python scripts/backfill.py --since 2024-01-01 [수집기 이름 ...]

수집기들은 평소에 '이미 저장한 글을 만나면 멈추는' 증분 수집이라 과거로 거슬러 가지 못한다.
그래서 기존 data 파일을 잠시 치워 두고 --since 날짜부터 새로 수집한 뒤, 기존 자료와 합친다(같은 id는 새 자료 우선).
각 수집기의 요청 간격(성장금융은 robots.txt의 60초 등)은 그대로 지킨다.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
# 수집기 파일 이름 -> data 파일 이름, 추가 인자(최대 페이지를 넉넉히)
JOBS = {
    "kvic": ("kvic.json", ["--max-pages", "400"]),
    "kdb": ("kdb.json", ["--max-pages", "200"]),
    "kif": ("kif.json", ["--max-pages", "200"]),
    "koreaexim": ("koreaexim.json", ["--max-pages", "200"]),
    "ktcu": ("ktcu.json", ["--max-pages", "200"]),
    "mmaa": ("mmaa.json", []),
    "nps": ("nps.json", ["--max-pages", "200"]),
    "ibk": ("ibk.json", ["--max-pages", "50"]),
    "shinhanam": ("shinhanam.json", ["--max-steps", "600"]),
    "shinhanvc": ("shinhanvc.json", ["--max-pages", "50"]),
    "wooriam": ("wooriam.json", ["--max-pages", "50"]),
    "kiwoom": ("kiwoom.json", ["--max-pages", "20"]),
    "kgrowth": ("kgrowth.json", ["--max-pages", "200"]),  # 요청 간격 60초라 가장 오래 걸려 맨 뒤에 둔다
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True)
    ap.add_argument("jobs", nargs="*", default=list(JOBS))
    args = ap.parse_args()
    for name in args.jobs:
        fname, extra = JOBS[name]
        path = DATA / fname
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        backup = path.with_suffix(".json.bak")
        if path.exists():
            shutil.copy2(path, backup)
            path.unlink()
        print(f"=== {name}: 기존 {len(old)}건, {args.since}부터 다시 수집", flush=True)
        rc = subprocess.run([sys.executable, str(ROOT / "scripts" / f"collect_{name}.py"),
                             "--since", args.since, *extra]).returncode
        new = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        merged = {str(it["id"]): it for it in old}
        merged.update({str(it["id"]): it for it in new})
        items = sorted(merged.values(), key=lambda x: (x["published"], str(x["id"])), reverse=True)
        path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        backup.unlink(missing_ok=True)
        print(f"=== {name}: 종료코드 {rc}, 새로 받은 {len(new)}건, 합친 뒤 {len(items)}건", flush=True)


if __name__ == "__main__":
    main()
