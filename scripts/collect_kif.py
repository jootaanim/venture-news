"""KIF투자조합(한국통신사업자연합회 KTOA 운영) 출자사업·업무집행조합원(GP) 공고 수집기.

주의: kif.or.kr 은 (사)한국산림데이터기술원 사이트로 무관하다. KIF투자조합 공고는 KTOA 사이트의
'알림마당 > 입찰공고' 게시판에 올라온다.
- 목록: https://www.ktoa.or.kr/ko/notice/bidding/page?pageIndex=N&listRowSize=50 (HTML 조각, JS가 채우는 XHR)
- 상세: https://www.ktoa.or.kr/ko/notice/bidding/view?detailsKey=ID
- 게시판에는 일반 입찰(용역 등)도 섞여 있어 제목 키워드로 KIF 출자 관련만 남긴다.
- 기본 수집 기간: 최근 6개월(--since로 변경). 이미 저장한 id를 만나면 증분 수집.
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

BASE = "https://www.ktoa.or.kr"
BOARD = "/ko/notice/bidding"
OUT = Path(__file__).resolve().parent.parent / "data" / "kif.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; venture-news-bot/0.1)"}
DELAY = 1.0
PAGE_SIZE = 50
KEYWORDS = ("KIF", "출자", "위탁운용", "업무집행", "자펀드", "GP", "투자조합", "모태펀드")


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
    if "접수" in title:
        return "접수현황"
    if "선정" in title and "결과" in title:
        return "선정결과"
    if ("심의" in title or "서류" in title) and "결과" in title:
        return "서류결과"
    if any(k in title for k in ("계획", "공고", "설명회", "모집", "공모")):
        return "출자계획"
    return "기타"


def relevant(title):
    return any(k in title for k in KEYWORDS)


def parse_list(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for a in soup.select("a.listView"):
        key = a.get("data-details-key")
        t = a.select_one("p.title")
        d = a.select_one("p.date")
        if not (key and t and d):
            continue
        rows.append({"id": int(key), "title": clean(t.get_text()),
                     "published": d.get_text(strip=True).replace(".", "-")})
    return rows


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one("div.txt-area")
    body = node.get_text("\n", strip=True).replace("​", "") if node else ""
    attachments = []
    for a in soup.select("div.attatched-file-area a.download[href]"):
        attachments.append({"name": clean(a.get_text()), "url": f"{BASE}{a['href']}"})
    return {"attachments": attachments, "body": body}


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
    ap.add_argument("--since", default=str(date.today() - timedelta(days=183)),
                    help="이 날짜 이전 글은 수집하지 않음 (YYYY-MM-DD)")
    ap.add_argument("--max-pages", type=int, default=50)
    args = ap.parse_args()

    items = load()
    known = set(items)
    new_count = 0
    for page in range(1, args.max_pages + 1):
        rows = parse_list(get(f"{BOARD}/page", pageIndex=page, pageRowSize=10,
                              listRowSize=PAGE_SIZE, q=""))
        if not rows:
            print(f"{page}페이지: 글 없음, 종료")
            break
        hit_known = any(r["id"] in known for r in rows)
        fresh = [r for r in rows if r["id"] not in known]
        in_range = [r for r in fresh if r["published"] >= args.since and relevant(r["title"])]
        print(f"{page}페이지: {len(rows)}건 중 신규 {len(fresh)}건, 기간 내 관련 {len(in_range)}건")
        for r in in_range:
            time.sleep(DELAY)
            detail = parse_detail(get(f"{BOARD}/view", detailsKey=r["id"]))
            items[r["id"]] = {
                "id": r["id"],
                "source": "KIF",
                "kind": "notice",
                "category": classify(r["title"]),
                "title": r["title"],
                "published": r["published"],
                "url": f"{BASE}{BOARD}/view?detailsKey={r['id']}",
                **detail,
            }
            new_count += 1
        if hit_known or all(r["published"] < args.since for r in rows):
            break
        time.sleep(DELAY)

    save(items)
    print(f"완료: 신규 {new_count}건, 전체 {len(items)}건 -> {OUT}")


if __name__ == "__main__":
    main()
