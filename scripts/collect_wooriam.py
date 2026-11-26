"""우리자산운용 출자사업(국민성장펀드 초장기기술투자펀드 등 위탁운용사 선정) 공고 수집기.

- 게시판: https://www.wooriam.kr/customer/notice-list?pageNo=N (robots.txt: 전체 허용)
- 상세: https://www.wooriam.kr/customer/notice-view/{코드} (GET으로 바로 열림)
- 게시판에는 입찰공고·채용 등 무관한 글도 있어 제목 키워드로 출자 관련만 남긴다.
- 기본 수집 기간: 최근 6개월(--since). 이미 저장한 글은 건너뛴다.
"""
import argparse
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://www.wooriam.kr"
OUT = Path(__file__).resolve().parent.parent / "data" / "wooriam.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; venture-news-bot/0.1)"}
DELAY = 1.0
KEYWORDS = ("위탁운용", "출자", "초장기기술투자펀드", "국민성장펀드")


def get(path, **params):
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE}{path}", params=params, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r.content.decode("utf-8", errors="replace")
        except requests.RequestException as e:
            print(f"  요청 실패({attempt + 1}/3): {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"요청 3회 실패: {path} {params}")


def clean(s):
    return re.sub(r"\s+", " ", s.replace("​", "")).strip()


def classify(title):
    if "공청회" in title or "설명회" in title:
        return "기타"
    if "질의" in title or "FAQ" in title:
        return "질의응답"
    if "접수" in title:
        return "접수현황"
    if "서류" in title and "결과" in title:
        return "서류결과"
    if "선정" in title and "결과" in title:
        return "선정결과"
    if any(k in title for k in ("계획", "공고", "모집", "공모")):
        return "출자계획"
    return "기타"


def parse_list(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for item in soup.select("div.board-item"):
        a = item.select_one("a[href*='goView']")
        d = item.select_one("p.board-item__date")
        if not (a and d):
            continue
        m = re.search(r"goView\('([^']+)',\s*'([^']+)'", a["href"])
        if not m:
            continue
        rows.append({"id": m.group(2), "path": m.group(1), "title": clean(a.get_text()),
                     "published": d.get_text(strip=True).replace(".", "-")})
    return rows


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    files = [{"name": clean(a.get_text()), "url": f"{BASE}{a['href']}"}
             for a in soup.select("a.layout-board-view__download[href]")]
    node = soup.select_one("div.layout-board-view__content, div.layout-board-view__body")
    return {"attachments": files, "body": node.get_text("\n", strip=True) if node else ""}


def load():
    if OUT.exists():
        return {it["id"]: it for it in json.loads(OUT.read_text(encoding="utf-8"))}
    return {}


def save(items):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = sorted(items.values(), key=lambda x: (x["published"], x["id"]), reverse=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=str(date.today() - timedelta(days=183)))
    ap.add_argument("--max-pages", type=int, default=10)
    args = ap.parse_args()

    items = load()
    new_count = 0
    for page in range(1, args.max_pages + 1):
        rows = parse_list(get("/customer/notice-list", pageNo=page))
        if not rows:
            break
        pick = [r for r in rows if r["id"] not in items and r["published"] >= args.since
                and any(k in r["title"] for k in KEYWORDS)]
        print(f"{page}페이지: {len(rows)}건 중 기간 내 신규 관련 {len(pick)}건")
        for r in pick:
            time.sleep(DELAY)
            d = parse_detail(get(f"{r['path']}/{r['id']}"))
            items[r["id"]] = {"id": r["id"], "source": "우리자산운용", "kind": "notice",
                              "category": classify(r["title"]), "title": r["title"],
                              "published": r["published"], "url": f"{BASE}{r['path']}/{r['id']}", **d}
            new_count += 1
        if all(r["published"] < args.since for r in rows):
            break
        time.sleep(DELAY)
    save(items)
    print(f"완료: 신규 {new_count}건, 전체 {len(items)}건 -> {OUT}")


if __name__ == "__main__":
    main()
