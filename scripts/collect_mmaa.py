"""군인공제회 위탁운용사(GP) 선정 공고·결과 수집기.

게시판: https://www.mmaa.or.kr/web/contents/notice.do (홈페이지 > 소식·정보 > 공지사항)
- 목록은 서버 렌더링 HTML(?page=N&viewCount=20), 상세는 ?schM=view&id=글번호 (고유 주소).
- 첨부는 /afile/fileList.do?fileId=... JSON 으로 조회, 다운로드 경로는 downloadPath.
- robots.txt: 사이트에 robots.txt 가 없다(요청 시 200 + 'Page Not Found' HTML). 별도 Disallow/Crawl-delay 없음.
- 상단 고정글(fn_goView 두 번째 인자 'inotice')은 기간 종료/증분 종료 판단에서 제외한다.
- 제목 키워드로 무관한 공지를 거른다. 기본 수집 기간: 오늘-183일. 이미 저장된 id를 만나면 멈춘다.
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

BASE = "https://www.mmaa.or.kr"
BOARD_URL = f"{BASE}/web/contents/notice.do"
OUT = Path(__file__).resolve().parent.parent / "data" / "mmaa.json"
HEADERS = {"User-Agent": "venture-news-bot/0.1 (research; contact via repository owner)"}
DELAY = 1.0
PAGE_SIZE = 20
KEYWORDS = ["위탁운용", "선정", "블라인드", "벤처", "VC", "PE", "펀드", "운용사", "GP", "출자"]
EXCLUDE = ["부동산", "매각", "입찰", "채용"]
session = requests.Session()
session.headers.update(HEADERS)
_last = 0.0


def get(url, params=None, as_json=False):
    global _last
    for attempt in range(3):
        wait = DELAY - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        try:
            r = session.get(url, params=params, timeout=30)
            _last = time.time()
            r.raise_for_status()
            return r.json() if as_json else r.content.decode("utf-8", errors="replace")
        except (requests.RequestException, ValueError) as e:
            _last = time.time()
            print(f"  요청 실패({attempt + 1}/3): {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"요청 3회 실패: {url}")


def relevant(title):
    t = title.upper()
    if any(x.upper() in t for x in EXCLUDE):
        return False
    return any(k.upper() in t for k in KEYWORDS)


def categorize(title):
    if "접수현황" in title or "접수 현황" in title:
        return "접수현황"
    if "서류" in title and "결과" in title:
        return "서류결과"
    if "결과" in title or "최종 선정" in title or "선정 완료" in title:
        return "선정결과"
    if "선정계획" in title or "선정 계획" in title or "출자계획" in title or "출자 계획" in title:
        return "출자계획"
    if "선정 공고" in title or "선정공고" in title or "공모" in title:
        return "출자계획"
    return "기타"


def parse_list(html):
    rows = []
    for tr in BeautifulSoup(html, "html.parser").find_all("tr"):
        a = tr.find("a", onclick=True)
        m = a and re.search(r"fn_goView\('(\d+)'(?:\s*,\s*'(\w+)')?\)", a["onclick"])
        td = tr.find_all("td")
        if not m or len(td) < 4:
            continue
        d = td[-2].get_text(strip=True)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            continue
        rows.append({"id": m.group(1), "pinned": bool(m.group(2)),
                     "title": re.sub(r"\s+", " ", a.get_text()).strip(), "published": d})
    return rows


def fetch_detail(id_):
    url = f"{BOARD_URL}?schM=view&id={id_}"
    html = get(url)
    soup = BeautifulSoup(html, "html.parser")
    box = soup.select_one("div.b_content")
    body = re.sub(r"\n{3,}", "\n\n", box.get_text("\n", strip=True)) if box else ""
    atts = []
    m = re.search(r'/afile/fileList\.do",\s*data:\s*"fileId=([^"]+)"', html)
    if m:
        try:
            for f in get(f"{BASE}/afile/fileList.do", {"fileId": m.group(1)}, as_json=True):
                if f.get("downloadPath"):
                    atts.append({"name": f.get("fileName", ""), "url": BASE + f["downloadPath"]})
        except RuntimeError as e:
            print(f"  첨부 조회 실패 id={id_}: {e}", file=sys.stderr)
    return url, body, atts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=(date.today() - timedelta(days=183)).isoformat())
    args = ap.parse_args()
    existing = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    known = {r["id"] for r in existing}
    new = []
    page, stop = 1, False
    while not stop and page <= 100:
        rows = parse_list(get(BOARD_URL, {"schM": "list", "page": page, "viewCount": PAGE_SIZE}))
        if not rows:
            break
        for r in rows:
            if r["pinned"]:
                continue
            if r["published"] < args.since:
                stop = True
                break
            rid = "mmaa-" + r["id"]
            if rid in known:
                stop = True
                break
            if not relevant(r["title"]):
                continue
            url, body, atts = fetch_detail(r["id"])
            new.append({"id": rid, "source": "군인공제회", "kind": "notice",
                        "category": categorize(r["title"]), "title": r["title"],
                        "published": r["published"], "url": url, "attachments": atts, "body": body})
            print(f"  + {r['published']} {r['title']}")
        page += 1
    merged = sorted(new + existing, key=lambda x: (x["published"], x["id"]), reverse=True)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"신규 {len(new)}건, 전체 {len(merged)}건 (since={args.since})")


if __name__ == "__main__":
    main()
