"""과학기술인공제회(SEMA) 공지사항의 출자사업·위탁운용사 공고 수집기.

- robots.txt: 모든 봇에 /sema/bbs/B0000022/(공지사항) 허용. 첨부파일 경로(/sema/cmmn/file/)는 금지라 받지 않는다.
- 서버가 매우 느리고(한 번에 20~30초) 일반적인 Accept 헤더가 없는 요청에는 응답하지 않아, 표준 Accept 헤더를 붙인다.
- 게시판 글이 많아(공지 800여 건) 목록을 넘기지 않고 제목 검색 결과만 읽는다(검색어마다 요청 1번).
  검색: /sema/bbs/B0000022/list.do?menuNo=200017&searchCnd=1&searchWrd=검색어
- 상세: /sema/bbs/B0000022/view.do?nttId=번호&menuNo=200017
- 주식·채권 펀드 위탁운용사 공고도 함께 걸리므로, 벤처캐피탈 관련만 사이트에 싣는 거름은 build_site.py(MIXED_BOARDS)가 한다.
- 기본 수집 기간: 최근 6개월(--since).
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

BASE = "https://www.sema.or.kr"
LIST = "/sema/bbs/B0000022/list.do"
OUT = Path(__file__).resolve().parent.parent / "data" / "sema.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; venture-news-bot/0.1)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
DELAY = 3.0
SEARCH_WORDS = ("출자", "위탁운용", "블라인드", "VC")


def get(params):
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE}{LIST}", params=params, headers=HEADERS, timeout=(20, 120))
            r.raise_for_status()
            return r.content.decode("utf-8", errors="replace")
        except requests.RequestException as e:
            print(f"  요청 실패({attempt + 1}/3): {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"요청 3회 실패: {params}")


def clean(s):
    return re.sub(r"\s+", " ", s.replace("​", "")).strip()


def classify(title):
    if "질의" in title or "FAQ" in title:
        return "질의응답"
    if "접수" in title:
        return "접수현황"
    if ("서류" in title or "1차" in title) and "결과" in title:
        return "서류결과"
    if "선정" in title and "결과" in title:
        return "선정결과"
    if any(k in title for k in ("계획", "공고", "설명회", "모집", "공모")):
        return "출자계획"
    return "기타"


def parse_list(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("table.dataTbl tbody tr"):
        a = tr.select_one("a.aLink[href]")
        d = re.search(r"\d{4}-\d{2}-\d{2}", tr.get_text(" "))
        m = re.search(r"nttId=(\d+)", a["href"]) if a else None
        if not (a and d and m):
            continue
        rows.append({"id": int(m.group(1)), "title": clean(a.get_text()), "published": d.group(0)})
    return rows


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
    args = ap.parse_args()

    items = load()
    new_count = 0
    for i, word in enumerate(SEARCH_WORDS):
        if i:
            time.sleep(DELAY)
        try:
            rows = parse_list(get({"menuNo": "200017", "searchCnd": "1", "searchWrd": word, "pageIndex": "1"}))
        except RuntimeError as e:  # 서버가 자주 시간 초과된다. 이번 검색만 건너뛰고 나머지는 저장한다.
            print(f"'{word}' 검색 건너뜀: {e}", file=sys.stderr)
            continue
        pick = [r for r in rows if r["id"] not in items and r["published"] >= args.since]
        print(f"'{word}' 검색: {len(rows)}건 중 기간 내 신규 {len(pick)}건")
        for r in pick:
            items[r["id"]] = {"id": r["id"], "source": "과학기술인공제회", "kind": "notice",
                              "category": classify(r["title"]), "title": r["title"], "published": r["published"],
                              "url": f"{BASE}/sema/bbs/B0000022/view.do?nttId={r['id']}&menuNo=200017",
                              "attachments": []}
            new_count += 1
    save(items)
    print(f"완료: 신규 {new_count}건, 전체 {len(items)}건 -> {OUT}")


if __name__ == "__main__":
    main()
