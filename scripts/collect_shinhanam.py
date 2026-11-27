"""신한자산운용 출자사업(위탁운용사 선정) 공고 수집기.

- 게시판: https://www.shinhanfund.com/ko/pc/board/notice (robots.txt: 전체 허용)
- 목록은 최신 10건만 서버가 내려주고 더 보는 방법이 없어, 글 번호가 연속인 점을 이용해
  상세 주소(noticeView?no=N)를 최신 번호부터 거꾸로 읽는다.
- 상세: https://www.shinhanfund.com/ko/pc/board/noticeView?no=N
- 게시판에는 서비스 안내 등 무관한 글도 있어 제목 키워드로 출자 관련만 남긴다.
- 기본 수집 기간: 최근 6개월(--since). 이미 저장한 번호는 건너뛰는 증분 수집.
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

BASE = "https://www.shinhanfund.com"
LIST = "/ko/pc/board/notice"
VIEW = "/ko/pc/board/noticeView"
OUT = Path(__file__).resolve().parent.parent / "data" / "shinhanam.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; venture-news-bot/0.1)"}
DELAY = 1.0
KEYWORDS = ("출자", "위탁운용", "혁신펀드", "정책성펀드", "펀드 선정", "자펀드", "모태")


def get(path, **params):
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE}{path}", params=params, headers=HEADERS, timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content.decode("utf-8", errors="replace")
        except requests.RequestException as e:
            print(f"  요청 실패({attempt + 1}/3): {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"요청 3회 실패: {path} {params}")


def clean(s):
    return re.sub(r"\s+", " ", s.replace("​", "")).strip()


def classify(title):
    if "FAQ" in title or "질의" in title:
        return "질의응답"
    if "접수" in title:
        return "접수현황"
    if "서류" in title and "결과" in title:
        return "서류결과"
    if "선정" in title and "결과" in title:
        return "선정결과"
    if any(k in title for k in ("계획", "공고", "설명회", "모집", "공모")):
        return "출자계획"
    return "기타"


def relevant(title):
    return any(k in title for k in KEYWORDS)


def latest_id():
    html = get(LIST)
    ids = [int(x) for x in re.findall(r"noticeView\?no=(\d+)", html)]
    return max(ids)


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    t = soup.select_one("h2.bv-title")
    d = soup.select_one("span.bv-date")
    if not (t and d):
        return None
    body = soup.select_one("div.board-cont")
    files = []
    for a in soup.select("dl.board-attach a.atc-link[href]"):
        name = a.select_one("span.atc-name")
        files.append({"name": clean(name.get_text()) if name else "첨부파일", "url": f"{BASE}{a['href']}"})
    return {"title": clean(t.get_text()), "published": d.get_text(strip=True).replace(".", "-"),
            "body": body.get_text("\n", strip=True) if body else "", "attachments": files}


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
    ap.add_argument("--max-steps", type=int, default=400)
    args = ap.parse_args()

    items = load()
    new_count = 0
    top = latest_id()
    for n in range(top, max(top - args.max_steps, 0), -1):
        if n in items:
            break  # 저장된 가장 최근 글을 만나면 그보다 오래된 글은 이미 처리한 것
        time.sleep(DELAY)
        try:
            html = get(VIEW, no=n)
        except RuntimeError as e:  # 지워졌거나 서버 오류가 나는 글 번호는 건너뛴다
            print(f"no={n} 건너뜀: {e}", file=sys.stderr)
            continue
        d = parse_detail(html) if html else None
        if not d:
            continue
        if d["published"] < args.since:
            print(f"no={n} {d['published']}: 기간 밖, 종료")
            break
        if not relevant(d["title"]):
            continue
        items[n] = {"id": n, "source": "신한자산운용", "kind": "notice", "category": classify(d["title"]),
                    "title": d["title"], "published": d["published"],
                    "url": f"{BASE}{VIEW}?no={n}", "attachments": d["attachments"], "body": d["body"]}
        new_count += 1
    save(items)
    print(f"완료: 신규 {new_count}건, 전체 {len(items)}건 -> {OUT}")


if __name__ == "__main__":
    main()
