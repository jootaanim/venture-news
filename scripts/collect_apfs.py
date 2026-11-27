"""농업정책보험금융원(농림수산식품모태펀드) 공지사항의 출자사업 공고 수집기.

허용 근거: 농금원 robots.txt는 모든 수집기를 막고 있으나(Disallow: /), 사이트 운영자가 농금원에
수집 허용을 요청해 2026-11-27 허용 답변을 받았다(docs/수집허용.md). 허용 범위가 바뀌면 이 수집기를 끈다.

- 목록: POST https://www.apfs.kr/front/board/boardContentsList.do (miv_pageNo=N, 한 페이지 15건)
- 상세: https://www.apfs.kr/front/board/boardContentsView.do?boardId=10026&menuId=41&contId=번호 (GET으로 열림)
- 목록만 읽고(상세·첨부파일은 받지 않음) 이미 저장한 글까지 오면 멈춘다. 요청 간격 3초.
- 게시판에는 채용·행사 안내도 섞여 있어 제목 키워드로 출자사업 관련만 남긴다. 기본 수집 기간: 최근 6개월.
"""
import argparse
import html as htmllib
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://www.apfs.kr"
LIST = "/front/board/boardContentsList.do"
VIEW = "/front/board/boardContentsView.do?boardId=10026&menuId=41&contId={}"
OUT = Path(__file__).resolve().parent.parent / "data" / "apfs.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; venture-news-bot/0.1)",
           "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
DELAY = 3.0
PAGE_SIZE = 15
KEYWORDS = re.compile(r"출자사업|업무집행조합원|위탁운용사|운용사 선정|GP 선정")


def get(page):
    data = {"miv_pageNo": page, "miv_pageSize": PAGE_SIZE, "boardId": "10026", "menuId": "41",
            "searchKey": "A", "searchTxt": "", "delYn": "N", "mode": "W"}
    for attempt in range(3):
        try:
            r = requests.post(f"{BASE}{LIST}", data=data, headers=HEADERS, timeout=40)
            r.raise_for_status()
            return r.content.decode("utf-8", errors="replace")
        except requests.RequestException as e:
            print(f"  요청 실패({attempt + 1}/3): {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"요청 3회 실패: {page}페이지")


def clean(s):
    return re.sub(r"\s+", " ", htmllib.unescape(s).replace("​", "")).strip()


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


def parse_list(page_html):
    soup = BeautifulSoup(page_html, "html.parser")
    rows = []
    for tr in soup.select("table.tstyle_list tbody tr"):
        a = tr.select_one("a.detail_view[viewId], a.detail_view[viewid]")
        d = tr.select_one("td.c_reg_dt")
        if not (a and d):
            continue
        pinned = bool(tr.select_one("td.c_number img"))
        files = [img.get("alt", "") for img in tr.select("td.c_attach img") if img.get("alt")]
        rows.append({"id": int(a.get("viewid") or a.get("viewId")), "title": clean(a.get_text()),
                     "published": d.get_text(strip=True), "pinned": pinned, "files": files})
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
    ap.add_argument("--max-pages", type=int, default=5)
    args = ap.parse_args()

    items = load()
    new_count = 0
    for page in range(1, args.max_pages + 1):
        if page > 1:
            time.sleep(DELAY)
        rows = parse_list(get(page))
        if not rows:
            break
        pick = [r for r in rows if r["id"] not in items and r["published"] >= args.since and KEYWORDS.search(r["title"])]
        print(f"{page}페이지: {len(rows)}건 중 기간 내 신규 출자 관련 {len(pick)}건")
        for r in pick:
            items[r["id"]] = {"id": r["id"], "source": "농업정책보험금융원", "kind": "notice",
                              "category": classify(r["title"]), "title": r["title"], "published": r["published"],
                              "url": BASE + VIEW.format(r["id"]),
                              "attachments": [{"name": n, "url": ""} for n in r["files"]]}
            new_count += 1
        normal = [r for r in rows if not r["pinned"]]  # 맨 위 고정글은 매 페이지 반복되므로 멈춤 판단에서 뺀다
        if not normal or all(r["id"] in items for r in normal) or all(r["published"] < args.since for r in normal):
            break
    save(items)
    print(f"완료: 신규 {new_count}건, 전체 {len(items)}건 -> {OUT}")


if __name__ == "__main__":
    main()
