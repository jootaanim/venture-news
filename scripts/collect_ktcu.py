"""한국교직원공제회(KTCU) 위탁운용사(GP) 선정 공고 수집기.

게시판: https://www.ktcu.or.kr/PPW-CSB-000101 (공지사항). 목록은 POST(curPage), 상세는 GET /PPW-CSB-000101/{nttNo}.
robots.txt: Allow / , Disallow /workPage.html (Crawl-delay 없음). 사용 경로는 허용됨.
기본 수집 기간: 최근 183일. 이미 저장한 id를 만나면 증분 종료.
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

BASE = "https://www.ktcu.or.kr"
BOARD_URL = f"{BASE}/PPW-CSB-000101"
OUT = Path(__file__).resolve().parent.parent / "data" / "ktcu.json"
HEADERS = {"User-Agent": "venture-news-bot/0.1 (research; honest crawler)"}
DELAY = 1.0
KEYWORDS = ["위탁운용", "선정", "블라인드", "벤처", "VC", "PEF", "펀드", "운용사", "GP", "출자", "모펀드"]
EXCLUDE = ["입찰", "용역", "채용"]
_last = [0.0]


def get(url, data=None):
    for attempt in range(3):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            _last[0] = time.time()
            r = requests.post(url, data=data, headers=HEADERS, timeout=40) if data is not None \
                else requests.get(url, headers=HEADERS, timeout=40)
            r.raise_for_status()
            r.encoding = "utf-8"
            return r.text
        except requests.RequestException as e:
            print(f"  요청 실패({attempt + 1}/3): {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"요청 3회 실패: {url}")


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ").replace("​", "")).strip()


def relevant(title):
    t = title.upper()
    if any(x in t for x in EXCLUDE):
        return False
    return any(k.upper() in t for k in KEYWORDS)


def classify(t):
    if re.search(r"서류\s*(심사)?\s*(결과|합격)|서류심사|발표심사|면접", t):
        return "서류결과"
    if re.search(r"접수\s*(현황|결과)|지원\s*현황", t):
        return "접수현황"
    if re.search(r"선정\s*결과|최종\s*선정|우선협상|선정\s*(운용사|GP)\s*(발표|안내)", t):
        return "선정결과"
    if re.search(r"선정\s*계획|선정\s*공고|모집|출자\s*계획|출자사업|공고", t):
        return "출자계획"
    return "기타"


def parse_list(html):
    rows = []
    for li in BeautifulSoup(html, "html.parser").select("li"):
        a = li.select_one("span.tit a")
        m = re.search(r"fn_view\('(\d+)'\)", a.get("href", "")) if a else None
        d = li.select_one("span.date")
        if not (m and d and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.get_text(strip=True))):
            continue
        num = li.select_one("span.num")
        rows.append({"id": int(m.group(1)), "title": clean(a.get_text()),
                     "published": d.get_text(strip=True),
                     "pinned": not (num and num.get_text(strip=True).isdigit())})
    return rows


def parse_detail(html):
    s = BeautifulSoup(html, "html.parser")
    cont = s.select_one("div.notice-cont")
    body = ""
    if cont:
        for x in cont.select('[style*="display:none"]'):
            x.decompose()
        body = "\n".join(l.strip() for l in cont.get_text("\n", strip=True).replace("\xa0", " ").splitlines() if l.strip())
    atts = [{"name": clean(a.get_text()), "url": BASE + a["href"] if a["href"].startswith("/") else a["href"]}
            for a in s.select("ul.file-list a[href]")]
    return body, atts


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
    ap.add_argument("--max-pages", type=int, default=40)
    args = ap.parse_args()
    items = load()
    known = set(items)
    new = 0
    for page in range(1, args.max_pages + 1):
        rows = parse_list(get(BOARD_URL, {"curPage": page, "srchCtgry": "", "srchKey": "", "srchText": ""}))
        if not rows:
            print(f"{page}페이지: 글 없음, 종료")
            break
        normal = [r for r in rows if not r["pinned"]] or rows
        added = 0
        for r in rows:
            if r["id"] in known or r["published"] < args.since or not relevant(r["title"]):
                continue
            body, atts = parse_detail(get(f"{BOARD_URL}/{r['id']}"))
            items[r["id"]] = {"id": r["id"], "source": "교직원공제회", "kind": "notice",
                              "category": classify(r["title"]), "title": r["title"],
                              "published": r["published"], "url": f"{BOARD_URL}/{r['id']}",
                              "attachments": atts, "body": body}
            added += 1
            new += 1
        print(f"{page}페이지: {len(rows)}건, 신규 {added}건")
        if all(r["published"] < args.since for r in normal) or any(r["id"] in known for r in normal):
            break
    save(items)
    print(f"신규 {new}건, 총 {len(items)}건 -> {OUT}")


if __name__ == "__main__":
    main()
