"""한국벤처투자(KVIC) 출자사업공지 수집기.

목록(?pageNo=N)을 읽어 새 글만 상세 페이지(?id=N)까지 받아 data/kvic.json에 누적한다.
- 처음 실행: --since 날짜(기본 2년 전)까지 거슬러 올라가며 수집
- 이후 실행: 이미 저장된 id를 만나면 중단(증분 수집)
- 날짜·접수마감 같은 '일정'은 여기서 추출하지 않는다(첨부 PDF 단계에서 처리).
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

BASE = "https://www.kvic.or.kr"
LIST_URL = BASE + "/notice/kvic-notice/investment-business-notice"
OUT = Path(__file__).resolve().parent.parent / "data" / "kvic.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; venture-news-bot/0.1)"}
DELAY = 1.0  # 서버 부담을 줄이기 위한 요청 간격(초)


def get(url, **params):
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            r.raise_for_status()
            r.encoding = r.encoding or "utf-8"
            return r.text
        except requests.RequestException as e:
            print(f"  요청 실패({attempt + 1}/3): {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"요청 3회 실패: {url} {params}")


def parse_list(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("tbody.data-List tr"):
        a = tr.select_one("td.board-subject a")
        if not a:
            continue
        m = re.search(r"board_view\((\d+)\)", a.get("href", ""))
        if not m:
            continue
        tds = tr.find_all("td")
        cat = tds[1].get_text(strip=True).strip("[]") if len(tds) > 1 else ""
        rows.append({
            "id": int(m.group(1)),
            "no": tds[0].get_text(strip=True),
            "category": cat,
            "title": a.get_text(strip=True),
            "published": tds[-1].get_text(strip=True),
        })
    return rows


def parse_detail(html, item_id):
    soup = BeautifulSoup(html, "html.parser")
    attachments = []
    seen = set()
    for a in soup.find_all("a", href=re.compile(r"fileDown\?boardDataNo=")):
        href = a["href"]
        if href in seen:
            continue
        seen.add(href)
        # 파일명은 같은 <div> 안의 <span>에 있다.
        holder = a.find_parent("div")
        span = holder.find("span") if holder else None
        name = span.get_text(strip=True) if span else ""
        attachments.append({"name": name, "url": BASE + href if href.startswith("/") else href})
    node = soup.select_one("div.board-conts")
    body = node.get_text("\n", strip=True) if node else ""
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
    ap.add_argument("--since", default=str(date.today() - timedelta(days=730)),
                    help="이 날짜 이전 글은 수집하지 않음 (YYYY-MM-DD)")
    ap.add_argument("--max-pages", type=int, default=200)
    args = ap.parse_args()

    items = load()
    known = set(items)
    new_count = 0
    for page in range(1, args.max_pages + 1):
        rows = parse_list(get(LIST_URL, pageNo=page))
        if not rows:
            print(f"{page}페이지: 글 없음, 종료")
            break
        fresh = [r for r in rows if r["id"] not in known]
        in_range = [r for r in fresh if r["published"] >= args.since]
        print(f"{page}페이지: {len(rows)}건 중 신규 {len(fresh)}건, 기간 내 {len(in_range)}건")
        for r in in_range:
            time.sleep(DELAY)
            detail = parse_detail(get(LIST_URL, id=r["id"]), r["id"])
            items[r["id"]] = {
                "id": r["id"],
                "source": "한국벤처투자",
                "kind": "notice",
                "category": r["category"],
                "title": r["title"],
                "published": r["published"],
                "url": f"{LIST_URL}?id={r['id']}",
                **detail,
            }
            new_count += 1
        # 이미 아는 글만 있는 페이지, 또는 기간을 벗어난 페이지에서 멈춘다.
        if not fresh or (rows and all(r["published"] < args.since for r in rows)):
            break
        time.sleep(DELAY)

    save(items)
    print(f"완료: 신규 {new_count}건, 전체 {len(items)}건 -> {OUT}")


if __name__ == "__main__":
    main()
