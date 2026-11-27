"""IBK기업은행 '은행공고' 게시판의 출자사업(위탁운용사 선정) 공고 수집기.

허용 근거: 기업은행 robots.txt는 모든 수집기를 막고 있으나(Disallow: /), 사이트 운영자가 기업은행에
수집 허용을 요청해 2026-11-27 허용 답변을 받았다(docs/수집허용.md). 허용 범위가 바뀌면 이 수집기를 끈다.

- 목록: https://www.ibk.co.kr/cyber/noticeListCyber.ibk?pageId=IR03010400&pageNum=N (GET, 한 페이지 10건)
- 상세: https://www.ibk.co.kr/cyber/noticeDetailCyber.ibk?pageId=IR03010400&srno=번호 (GET으로 열림)
- 첨부파일은 POST 다운로드(/common/download.ibk)라 받을 때 쓸 값을 함께 저장한다. 공고문은 extract_dates.py가 받는다
  (2026-11-27 첨부파일까지 허용 답변).
- 부담을 줄이기 위해 목록만 읽고(상세는 읽지 않음), 이미 저장한 글을 만나면 멈춘다. 요청 간격 3초.
- 게시판에는 채용·입찰 공고도 섞여 있어 제목 키워드로 출자 관련만 남긴다. 기본 수집 기간: 최근 6개월.
"""
import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://www.ibk.co.kr"
LIST = "/cyber/noticeListCyber.ibk"
DETAIL = "/cyber/noticeDetailCyber.ibk"
PAGE_ID = "IR03010400"
OUT = Path(__file__).resolve().parent.parent / "data" / "ibk.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; venture-news-bot/0.1)"}
DELAY = 3.0
KEYWORDS = ("위탁운용", "출자", "펀드", "운용사")


def get(**params):
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE}{LIST}", params={"pageId": PAGE_ID, **params}, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r.content.decode("utf-8", errors="replace")
        except requests.RequestException as e:
            print(f"  요청 실패({attempt + 1}/3): {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"요청 3회 실패: {params}")


def clean(s):
    return re.sub(r"\s+", " ", s.replace("​", "")).strip()


def classify(title):
    if "FAQ" in title or "질의" in title:
        return "질의응답"
    if "접수" in title or "지원 현황" in title or "지원현황" in title:
        return "접수현황"
    if "서류" in title and "결과" in title:
        return "서류결과"
    if "선정" in title and "결과" in title:
        return "선정결과"
    if any(k in title for k in ("계획", "공고", "설명회", "모집", "공모")):
        return "출자계획"
    return "기타"


def to_date(s):
    # 예: 'Tue Nov 17 00:00:00 KST 2026'
    m = re.search(r"([A-Z][a-z]{2}) (\d{1,2}) [\d:]+ \w+ (\d{4})", s)
    return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%b %d %Y").date().isoformat() if m else ""


def parse_list(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("tr"):
        a = tr.select_one("a[href*=viewThis], a[onclick*=viewThis]")
        if not a:
            continue
        m = re.search(r"viewThis\('(\d+)'", (a.get("href") or "") + (a.get("onclick") or ""))
        pub = to_date(tr.get_text(" "))
        if not (m and pub):
            continue
        files = []
        for x in tr.select("a"):
            m2 = re.search(r"downloadFile\('(\d+)','([^']*)','([^']*)',\s*'([^']*)'", x.get("href", "") + x.get("onclick", ""))
            if m2:  # 첨부파일은 POST로 받는다(/common/download.ibk). 받을 때 쓸 값을 같이 저장한다.
                files.append({"name": m2.group(3), "url": f"{BASE}/common/download.ibk",
                              "post": {"seq": m2.group(1), "fullName": m2.group(2), "fileName": m2.group(3),
                                       "category": "" if m2.group(4) == "null" else m2.group(4)}})
        rows.append({"id": int(m.group(1)), "title": clean(a.get_text()), "published": pub, "files": files})
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
        rows = parse_list(get(pageNum=page))
        if not rows:
            break
        fresh = [r for r in rows if r["id"] not in items]
        pick = [r for r in fresh if r["published"] >= args.since and any(k in r["title"] for k in KEYWORDS)]
        print(f"{page}페이지: {len(rows)}건 중 신규 {len(fresh)}건, 기간 내 출자 관련 {len(pick)}건")
        for r in pick:
            items[r["id"]] = {"id": r["id"], "source": "기업은행", "kind": "notice", "category": classify(r["title"]),
                              "title": r["title"], "published": r["published"],
                              "url": f"{BASE}{DETAIL}?pageId={PAGE_ID}&srno={r['id']}",
                              "attachments": r["files"]}
            new_count += 1
        if len(fresh) < len(rows) or all(r["published"] < args.since for r in rows):
            break
    save(items)
    print(f"완료: 신규 {new_count}건, 전체 {len(items)}건 -> {OUT}")


if __name__ == "__main__":
    main()
