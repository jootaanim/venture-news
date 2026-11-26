"""한국수출입은행 출자사업/위탁운용사(GP) 공고 수집기.

https://www.koreaexim.go.kr/HPHKBI039M01 (공지사항 게시판, 서버 렌더링 HTML, UTF-8)
- 목록: /HPHKBI039M01?curPage=N / 상세: /HPHKBI039M01/{id}
- 맨 위 고정글(순번 칸이 '공지' 아이콘)은 매 페이지 반복되므로 1페이지에서만 처리하고,
  기간 종료/증분 종료 판단에서는 제외한다.
- 출자사업과 무관한 일반 공지는 제목 키워드로 거른다.
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

from cabundle import ca_bundle

CA = ca_bundle()  # 서버가 빠뜨린 중간 인증서(certs/)를 더해 검증을 켠 채 접속
BASE = "https://www.koreaexim.go.kr"
BOARD = "HPHKBI039M01"
OUT = Path(__file__).resolve().parent.parent / "data" / "koreaexim.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; venture-news-bot/0.1)"}
DELAY = 1.0
KEYWORDS = ["출자", "위탁운용", "GP", "모펀드", "펀드", "운용사", "블라인드", "투자조합", "펀드", "벤처", "PEF", "VC"]


def get(path, **params):
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE}/{path}", params=params, headers=HEADERS, timeout=30, verify=CA)
            r.raise_for_status()
            return r.content.decode("utf-8", errors="replace")
        except requests.RequestException as e:
            print(f"  요청 실패({attempt + 1}/3): {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"요청 3회 실패: {path} {params}")


def clean(s):
    return re.sub(r"\s+", " ", s.replace("​", "").replace("\xa0", " ")).strip()


def relevant(title):
    t = title.upper()
    return any(k.upper() in t for k in KEYWORDS)


def classify(title):
    t = title
    if re.search(r"선정\s*결과|최종\s*선정|선정\s*공고|우선협상", t):
        return "선정결과"
    if re.search(r"서류\s*(심사)?\s*(결과|합격)|서류심사|PT|발표심사|심사\s*결과|면접", t):
        return "서류결과"
    if re.search(r"접수\s*현황|접수\s*결과|지원\s*현황|제안서\s*접수", t):
        return "접수현황"
    if re.search(r"모집|출자\s*계획|출자사업\s*(공고|계획)|공고|제안\s*요청", t):
        return "출자계획"
    return "기타"


def parse_list(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for item in soup.select("div.notice-list-item"):
        a = item.select_one("span.subject a[href]")
        if not a:
            continue
        m = re.search(rf"{BOARD}/(\d+)", a["href"])
        if not m:
            continue
        first = item.find("span")
        pinned = bool(first and first.get("title") == "공지")
        date_span = item.find("span", attrs={"title": "작성일"})
        d = clean(date_span.get_text()).replace(".", "-") if date_span else ""
        rows.append({"id": int(m.group(1)), "title": clean(a.get_text()),
                     "published": d, "pinned": pinned})
    return rows


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    body_node = soup.select_one("div.detail-view-box")
    body = body_node.get_text("\n", strip=True).replace("​", "").replace("\xa0", " ") if body_node else ""
    body = "\n".join(l.strip() for l in body.splitlines() if l.strip())
    attachments = []
    for a in soup.select("div.detail-view-file a[href]"):
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
    ap.add_argument("--max-pages", type=int, default=100)
    args = ap.parse_args()

    items = load()
    known = set(items)
    seen = set()
    new_count = 0
    for page in range(1, args.max_pages + 1):
        rows = parse_list(get(BOARD, curPage=page))
        if not rows:
            print(f"{page}페이지: 글 없음, 종료")
            break
        normal = [r for r in rows if not r["pinned"]]
        todo = []
        for r in rows:
            if r["id"] in known or r["id"] in seen:
                continue
            if r["pinned"] and page > 1:
                continue
            if r["published"] < args.since or not relevant(r["title"]):
                continue
            seen.add(r["id"])
            todo.append(r)
        print(f"{page}페이지: {len(rows)}건(고정 {len(rows) - len(normal)}), 수집 대상 {len(todo)}건")
        for r in todo:
            time.sleep(DELAY)
            detail = parse_detail(get(f"{BOARD}/{r['id']}", curPage=page))
            items[r["id"]] = {
                "id": r["id"],
                "source": "수출입은행",
                "kind": "notice",
                "category": classify(r["title"]),
                "title": r["title"],
                "published": r["published"],
                "url": f"{BASE}/{BOARD}/{r['id']}",
                **detail,
            }
            new_count += 1
        if not normal or all(r["published"] < args.since for r in normal):
            break
        if any(r["id"] in known for r in normal):
            break  # 증분: 이미 저장한 글에 도달
        time.sleep(DELAY)

    save(items)
    print(f"완료: 신규 {new_count}건, 전체 {len(items)}건 -> {OUT}")


if __name__ == "__main__":
    main()
