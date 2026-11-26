"""키움인베스트먼트 출자사업(키움 벤처히어로 모펀드 등) 공고 수집기.

- 게시판: https://www.kiwoominvest.com/bbs/index.php?so_table=notice (robots.txt는 특정 봇만 언급, 일반 봇 제한 없음)
- 상세: https://www.kiwoominvest.com/bbs/?so_table=notice&mode=VIEW&num=N
- 공지 게시판이라 글이 적다(수 건). 제목 키워드로 출자 관련만 남긴다.
- 기본 수집 기간: 최근 6개월(--since). 이미 저장한 번호는 건너뛴다.
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

BASE = "https://www.kiwoominvest.com"
OUT = Path(__file__).resolve().parent.parent / "data" / "kiwoom.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; venture-news-bot/0.1)"}
DELAY = 1.0
KEYWORDS = ("출자", "모펀드", "선정", "평가 결과", "위탁운용")


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
    if "질의" in title or "FAQ" in title:
        return "질의응답"
    if "접수" in title:
        return "접수현황"
    if "최종" in title and "결과" in title:
        return "선정결과"
    if ("평가" in title or "심사" in title or "서류" in title) and "결과" in title:
        return "서류결과"
    if "선정" in title and "결과" in title:
        return "선정결과"
    if any(k in title for k in ("계획", "공고", "설명회", "모집", "공모")):
        return "출자계획"
    return "기타"


def parse_list(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("table.colTbl tbody tr"):
        a = tr.select_one("td.title a[href]")
        tds = tr.select("td")
        if not a or len(tds) < 4:
            continue
        m = re.search(r"num=(\d+)", a["href"])
        if not m:
            continue
        rows.append({"id": int(m.group(1)), "title": clean(a.get_text()),
                     "published": tds[3].get_text(strip=True)})
    return rows


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    files = [{"name": clean(a.get_text()) or "첨부파일", "url": f"{BASE}{a['href']}"}
             for a in soup.select("a[href*='download.php']")]
    return {"attachments": files}


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
    ap.add_argument("--max-pages", type=int, default=5)
    args = ap.parse_args()

    items = load()
    new_count = 0
    for page in range(1, args.max_pages + 1):
        rows = parse_list(get("/bbs/index.php", so_table="notice", page=page))
        if not rows:
            break
        pick = [r for r in rows if r["id"] not in items and r["published"] >= args.since
                and any(k in r["title"] for k in KEYWORDS)]
        print(f"{page}페이지: {len(rows)}건 중 기간 내 신규 관련 {len(pick)}건")
        for r in pick:
            time.sleep(DELAY)
            url = f"{BASE}/bbs/?so_table=notice&mode=VIEW&num={r['id']}"
            d = parse_detail(get("/bbs/", so_table="notice", mode="VIEW", num=r["id"]))
            items[r["id"]] = {"id": r["id"], "source": "키움인베스트먼트", "kind": "notice",
                              "category": classify(r["title"]), "title": r["title"],
                              "published": r["published"], "url": url, **d}
            new_count += 1
        # 한 페이지가 꽉 차지 않았으면 마지막 페이지(없는 페이지를 요청하면 서버 오류가 난다)
        if len(rows) < 10 or all(r["published"] < args.since for r in rows):
            break
        time.sleep(DELAY)
    save(items)
    print(f"완료: 신규 {new_count}건, 전체 {len(items)}건 -> {OUT}")


if __name__ == "__main__":
    main()
