"""국민연금 기금운용본부 거래기관 선정공고(위탁운용사 등) 수집기.

게시판: https://fund.nps.or.kr/impa/dlnginstslctnpbanclist/getOHEF0017M0.do?menuId=MN24000492
 (알림 > 거래기관 선정공고)
- robots.txt: fund.nps.or.kr/robots.txt 는 404(규칙 없음). 목록/상세 경로는 제한 대상 아님.
- 목록 페이징은 화면이 호출하는 JSON POST(/impa/dlnginstslctnpbanclist/empty/getOHEF0017M0.do)를 그대로 쓴다.
- 상세는 POST 폼 이동이라 permalink가 없다. url은 게시판 주소 + '#pstId=글ID'.
- 첨부 다운로드 주소: /fileDown.do?atchFileId=..&atchFileSn=.. (링크만 저장, 내려받지 않음)
- 벤처·사모 위탁운용과 무관한 공고(해외, MMF, 부동산, 자문사, 은행 등)는 제목으로 거른다.
- 기본 수집 기간: 최근 183일. 이미 저장한 id를 만나면 증분 종료.
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

BASE = "https://fund.nps.or.kr"
BOARD_URL = f"{BASE}/impa/dlnginstslctnpbanclist/getOHEF0017M0.do?menuId=MN24000492"
LIST_API = f"{BASE}/impa/dlnginstslctnpbanclist/empty/getOHEF0017M0.do"
DETAIL_API = f"{BASE}/impa/dlnginstslctnpbancdtl/getOHEF0018M0.do"
OUT = Path(__file__).resolve().parent.parent / "data" / "nps.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; venture-news-bot/0.1)"}
DELAY = 1.0
KEYWORDS = ["위탁운용", "선정", "사모", "벤처", "블라인드", "펀드", "운용사", "GP", "출자"]
EXCLUDE = ["해외", "MMF", "부동산", "자문", "수탁", "은행", "증권", "채권", "주식", "인프라", "국내외", "국내·외", "금고", "리서치"]


def req(method, url, **kw):
    for attempt in range(3):
        try:
            r = requests.request(method, url, headers={**HEADERS, **kw.pop("headers", {})}, timeout=30, **kw)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            print(f"  요청 실패({attempt + 1}/3): {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"요청 3회 실패: {url}")


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def relevant(title):
    t = title.upper()
    if any(x.upper() in t for x in EXCLUDE):
        return False
    return any(k.upper() in t for k in KEYWORDS)


def classify(t):
    if re.search(r"서류\s*(심사)?\s*(결과|합격)|서류심사|발표심사|면접", t):
        return "서류결과"
    if re.search(r"접수\s*(현황|결과)|지원\s*현황", t):
        return "접수현황"
    if re.search(r"선정\s*결과|최종\s*선정|우선협상", t):
        return "선정결과"
    if re.search(r"선정\s*계획|모집|출자\s*계획|선정\s*공고|공고", t):
        return "출자계획"
    return "기타"


def list_page(page):
    html = req("POST", LIST_API, data=json.dumps({"pageIndex": page, "searchGbu": "", "searchText": ""}),
               headers={"Content-Type": "application/json;", "Accept": "application/json"})
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("tbody tr"):
        a = tr.select_one("td.title a")
        d = tr.select_one("td.date")
        if not a or not d:
            continue
        m = re.search(r"fnc_goBbsDetail\('([^']+)',\s*'([^']+)'", a.get("href", ""))
        if not m:
            continue
        rows.append({"id": m.group(1), "bbs": m.group(2), "title": clean(a.get_text()),
                     "published": d.get_text(strip=True).replace("/", "-")})
    return rows


def detail(pst_id, bbs):
    html = req("POST", DETAIL_API, data={"pstId": pst_id, "hmpgBbsCd": bbs})
    soup = BeautifulSoup(html, "html.parser")
    c = soup.select_one(".data-view-contents")
    body = "\n".join(l.strip() for l in (c.get_text("\n", strip=True) if c else "").replace("\xa0", " ").splitlines() if l.strip())
    atts, seen = [], set()
    for item in soup.select(".file-item"):
        a = item.select_one("a.btn-file-down")
        p = item.select_one("p.a-file")
        m = re.search(r"fncAtchFileDownload\('([^']+)',\s*'([^']+)'", a.get("href", "")) if a else None
        if not m or m.groups() in seen:
            continue
        seen.add(m.groups())
        name = re.sub(r"\s*\(\d+(\.\d+)?\s*[KMG]?B\)\s*$", "", clean(p.get_text() if p else ""))
        atts.append({"name": name, "url": f"{BASE}/fileDown.do?atchFileId={m.group(1)}&atchFileSn={m.group(2)}"})
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
    ap.add_argument("--max-pages", type=int, default=30)
    args = ap.parse_args()

    items = load()
    known = set(items)
    new_count = 0
    stop = False
    for page in range(1, args.max_pages + 1):
        rows = list_page(page)
        if not rows:
            print(f"{page}페이지: 글 없음, 종료")
            break
        added = 0
        for r in rows:
            if r["published"] < args.since:
                stop = True
                continue
            if r["id"] in known:
                stop = True
                continue
            if not relevant(r["title"]):
                continue
            time.sleep(DELAY)
            body, atts = detail(r["id"], r["bbs"])
            items[r["id"]] = {"id": r["id"], "source": "국민연금", "kind": "notice",
                              "category": classify(r["title"]), "title": r["title"],
                              "published": r["published"], "url": f"{BOARD_URL}#pstId={r['id']}",
                              "attachments": atts, "body": body}
            added += 1
            new_count += 1
        print(f"{page}페이지: {len(rows)}건, 신규 {added}건")
        if stop:
            break
        time.sleep(DELAY)
    save(items)
    print(f"완료: 신규 {new_count}건, 전체 {len(items)}건 -> {OUT}")


if __name__ == "__main__":
    main()
