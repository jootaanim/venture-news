"""한국산업은행(KDB) 출자사업/위탁운용사(GP) 공고 수집기.

게시판: https://www.kdb.co.kr/CHBIPR23N00.act (은행소개 > 새소식 > 공지사항, 통합게시판 ITR_BLB_ID=STD119)
- 화면은 JS가 JSON 서비스(POST /BOUBUF01R01.jct)를 호출해 그린다. 같은 서비스를 직접 호출한다.
  (robots.txt가 막는 /search*/ 경로는 사용하지 않는다.) 목록 응답에 본문 HTML과 첨부 정보가 들어 있다.
- 상세 화면은 POST 폼 이동이라 고유 주소(permalink)가 없다. url은 게시판 주소 + '#sno=게시글번호'로 만든다.
- 상단 고정글(ANC_YN=Y)은 기간 종료/증분 종료 판단에서 제외한다.
- 출자사업과 무관한 공지는 제목 키워드로 거른다.
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

BASE = "https://www.kdb.co.kr"
BOARD_URL = f"{BASE}/CHBIPR23N00.act"
API = f"{BASE}/BOUBUF01R01.jct"
BOARD_ID = "STD119"
FILE_URL = "https://file.kdb.co.kr/fileView"
OUT = Path(__file__).resolve().parent.parent / "data" / "kdb.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; venture-news-bot/0.1)",
           "Referer": BOARD_URL, "X-Requested-With": "XMLHttpRequest"}
DELAY = 1.0
PAGE_SIZE = 50
KEYWORDS = ["출자", "위탁운용", "GP", "모펀드", "펀드", "운용사", "블라인드", "선정계획", "투자조합", "PEF"]
EXCLUDE = ["입찰공고", "사전규격공개", "(긴급)", "용역", "위탁감리", "위탁운영", "수탁은행"]


def post(page):
    body = {"SEARCH_CONDITION": "", "SEARCH_KEYWORD": "", "SEARCH_CATEGORY": "", "ORDER_TYPE": "new",
            "MODE": "1,2,5,6", "ITR_BLB_ID": BOARD_ID,
            "HEADER_STD_WEB": {"REQ_PAGE_NO": page, "PAGE_ROW_COUNT": str(PAGE_SIZE),
                               "NEXT_PAGE_YN": "S" if page == 1 else "M",
                               "NEXTPAGDTT": "P", "GRID_NEXTKEY_ITR_CND": ""}}
    for attempt in range(3):
        try:
            r = requests.post(API, json=body, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return json.loads(r.content.decode("utf-8", errors="replace"))
        except (requests.RequestException, ValueError) as e:
            print(f"  요청 실패({attempt + 1}/3): {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"요청 3회 실패: page={page}")


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("​", "").replace("\xa0", " ")).strip()


def relevant(title):
    t = title.upper()
    if any(x.upper() in t for x in EXCLUDE):
        return False
    return any(k.upper() in t for k in KEYWORDS)


def classify(title):
    t = title
    if re.search(r"FAQ", t, re.I):
        return "기타"
    if re.search(r"서류\s*(심사)?\s*(결과|합격)|서류심사|발표심사|면접", t):
        return "서류결과"
    if re.search(r"접수\s*(현황|결과)|지원\s*현황", t):
        return "접수현황"
    if re.search(r"선정\s*결과|최종\s*선정|우선협상", t):
        return "선정결과"
    if re.search(r"선정\s*계획|모집|출자\s*계획|출자사업|공고", t):
        return "출자계획"
    return "기타"


def to_text(html):
    soup = BeautifulSoup(html or "", "html.parser")
    text = soup.get_text("\n", strip=True).replace("​", "").replace("\xa0", " ")
    return "\n".join(l.strip() for l in text.splitlines() if l.strip())


def parse_rows(data):
    files = {}
    for f in data.get("FILEGRPLIST_REC") or []:
        files.setdefault(f.get("GROUP_ID"), []).append(f)
    rows = []
    for x in data.get("STDLIST_REC") or []:
        d = (x.get("FST_ENR_DTM") or "")[:8]
        if len(d) != 8:
            continue
        atts = [{"name": clean(f.get("FILE_NM")),
                 "url": f"{FILE_URL}?groupId={f.get('GROUP_ID')}&fileId={f.get('FILE_ID')}"}
                for f in files.get(x.get("FILE_ID"), []) if x.get("FILE_ID")]
        rows.append({"id": int(x["ITR_NAC_ID_MNG_SNO"]), "title": clean(x.get("NAC_CONE_TTL")),
                     "published": f"{d[:4]}-{d[4:6]}-{d[6:]}", "pinned": x.get("ANC_YN") == "Y",
                     "body": to_text(x.get("NAC_HTML_TXT_INF")), "attachments": atts})
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
    ap.add_argument("--since", default=str(date.today() - timedelta(days=183)),
                    help="이 날짜 이전 글은 수집하지 않음 (YYYY-MM-DD)")
    ap.add_argument("--max-pages", type=int, default=40)
    args = ap.parse_args()

    items = load()
    known = set(items)
    seen = set()
    new_count = 0
    for page in range(1, args.max_pages + 1):
        rows = parse_rows(post(page))
        if not rows:
            print(f"{page}페이지: 글 없음, 종료")
            break
        normal = [r for r in rows if not r["pinned"]]
        added = 0
        for r in rows:
            if r["id"] in known or r["id"] in seen:
                continue
            if r["published"] < args.since or not relevant(r["title"]):
                continue
            seen.add(r["id"])
            items[r["id"]] = {
                "id": r["id"], "source": "산업은행", "kind": "notice",
                "category": classify(r["title"]), "title": r["title"],
                "published": r["published"], "url": f"{BOARD_URL}#sno={r['id']}",
                "attachments": r["attachments"], "body": r["body"],
            }
            added += 1
            new_count += 1
        print(f"{page}페이지: {len(rows)}건(고정 {len(rows) - len(normal)}), 신규 {added}건")
        if not normal or all(r["published"] < args.since for r in normal):
            break
        if any(r["id"] in known for r in normal):
            break  # 증분: 이미 저장한 글에 도달
        time.sleep(DELAY)

    save(items)
    print(f"완료: 신규 {new_count}건, 전체 {len(items)}건 -> {OUT}")


if __name__ == "__main__":
    main()
