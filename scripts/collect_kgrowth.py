"""한국성장금융 출자사업공고 수집기.

https://www.kgrowth.or.kr/notice.asp?tab=1 (클래식 ASP, EUC-KR)
- 목록: notice.asp?page=N&tab=1  / 상세: notice_view.asp?idx=ID&tab=1
- 제목이 "【카테고리】제목" 형식이라 카테고리를 분리한다.
- 맨 위 고정글(번호 칸에 이미지)은 매 페이지 반복되므로 건너뛴다.
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

BASE = "https://www.kgrowth.or.kr"
OUT = Path(__file__).resolve().parent.parent / "data" / "kgrowth.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; venture-news-bot/0.1)"}
DELAY = 60.0  # robots.txt의 Crawl-Delay: 60 준수 (증분 수집이라 매일 몇 건만 받는다)


def get(path, **params):
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE}/{path}", params=params, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r.content.decode("cp949", errors="replace")  # 사이트가 EUC-KR
        except requests.RequestException as e:
            print(f"  요청 실패({attempt + 1}/3): {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"요청 3회 실패: {path} {params}")


def clean(s):
    return re.sub(r"\s+", " ", s.replace("​", "")).strip()


def split_title(raw):
    m = re.match(r"^【(.+?)】\s*(.*)$", raw)
    return (m.group(1), m.group(2)) if m else ("", raw)


def parse_list(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("table.notice_tbl tr"):
        tds = tr.find_all("td")
        a = tr.find("a", href=re.compile(r"notice_view\.asp"))
        if len(tds) < 3 or not a:
            continue
        if not tds[0].get_text(strip=True).isdigit():
            continue  # 고정글
        m = re.search(r"idx=(\d+)", a["href"])
        if not m:
            continue
        cat, title = split_title(clean(a.get_text()))
        rows.append({"id": int(m.group(1)), "category": cat, "title": title,
                     "published": tds[2].get_text(strip=True)})
    return rows


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    body_node = soup.select_one("div.veiw_contents")
    body = body_node.get_text("\n", strip=True).replace("​", "") if body_node else ""
    attachments = []
    for a in soup.select("ul.file_list a[href]"):
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
    new_count = 0
    for page in range(1, args.max_pages + 1):
        rows = parse_list(get("notice.asp", page=page, tab=1))
        if not rows:
            print(f"{page}페이지: 글 없음, 종료")
            break
        fresh = [r for r in rows if r["id"] not in known]
        in_range = [r for r in fresh if r["published"] >= args.since]
        print(f"{page}페이지: {len(rows)}건 중 신규 {len(fresh)}건, 기간 내 {len(in_range)}건")
        for r in in_range:
            time.sleep(DELAY)
            detail = parse_detail(get("notice_view.asp", idx=r["id"], tab=1))
            items[r["id"]] = {
                "id": r["id"],
                "source": "한국성장금융",
                "kind": "notice",
                "category": r["category"],
                "title": r["title"],
                "published": r["published"],
                "url": f"{BASE}/notice_view.asp?idx={r['id']}&tab=1",
                **detail,
            }
            new_count += 1
        if not fresh or all(r["published"] < args.since for r in rows):
            break
        time.sleep(DELAY)

    save(items)
    print(f"완료: 신규 {new_count}건, 전체 {len(items)}건 -> {OUT}")


if __name__ == "__main__":
    main()
