"""벤처캐피탈·벤처기업 뉴스 수집기 (Google 뉴스 RSS).

제목, 원문 링크, 언론사, 발행일만 저장한다(본문은 저장·게시하지 않는다).
검색어별로 카테고리를 붙이고, 같은 제목은 하나로 합친다.
data/news.json에 누적하고 --keep-days보다 오래된 기사는 지운다.
"""
import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha1
from pathlib import Path
from urllib.parse import quote

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "news.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; venture-news-bot/0.1)"}
KST = timezone(timedelta(hours=9))

# (카테고리, 검색어). 검색어는 Google 뉴스 검색 문법을 따른다.
QUERIES = [
    ("VC·펀드", '벤처캐피탈 OR "벤처투자" OR "벤처펀드" OR "펀드 결성"'),
    ("출자·LP", '모태펀드 OR "출자사업" OR "위탁운용사" OR "성장금융" OR "벤처투자 출자"'),
    ("벤처기업", '스타트업 ("투자 유치" OR "시리즈A" OR "시리즈B" OR "시드 투자")'),
]


def fetch(query, days):
    q = quote(f"{query} when:{days}d")
    url = f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return ET.fromstring(r.content)
        except (requests.RequestException, ET.ParseError) as e:
            print(f"  요청 실패({attempt + 1}/3): {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"RSS 수집 실패: {query}")


def norm(title):
    return re.sub(r"[\W_]+", "", title).lower()


def parse(root, category):
    out = []
    for it in root.iter("item"):
        raw = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        src_el = it.find("source")
        outlet = (src_el.text or "").strip() if src_el is not None else ""
        if not raw or not link or not pub:
            continue
        if re.search(r"blog|블로그|tistory|brunch|cafe|카페|프리미엄콘텐츠", (src_el.text if src_el is not None else ""), re.I):
            continue  # 블로그·카페 등 언론이 아닌 출처 제외
        title = raw
        if outlet and raw.endswith(f" - {outlet}"):
            title = raw[: -len(f" - {outlet}")].strip()
        dt = parsedate_to_datetime(pub).astimezone(KST)
        out.append({
            "id": sha1(norm(title).encode()).hexdigest()[:12],
            "source": "뉴스",
            "kind": "article",
            "category": category,
            "outlet": outlet,
            "title": title,
            "published": dt.strftime("%Y-%m-%d"),
            "url": link,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="이번에 가져올 기간(일)")
    ap.add_argument("--keep-days", type=int, default=90, help="보관 기간(일)")
    args = ap.parse_args()

    items = {}
    if OUT.exists():
        for it in json.loads(OUT.read_text(encoding="utf-8")):
            items[it["id"]] = it

    new_count = 0
    for category, query in QUERIES:
        found = parse(fetch(query, args.days), category)
        added = 0
        for it in found:
            if it["id"] not in items:  # 같은 제목이 이미 있으면 먼저 들어온 카테고리 유지
                items[it["id"]] = it
                added += 1
        new_count += added
        print(f"[{category}] {len(found)}건 중 신규 {added}건")
        time.sleep(1)

    cutoff = (datetime.now(KST) - timedelta(days=args.keep_days)).strftime("%Y-%m-%d")
    items = {k: v for k, v in items.items() if v["published"] >= cutoff}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = sorted(items.values(), key=lambda x: (x["published"], x["id"]), reverse=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"완료: 신규 {new_count}건, 전체 {len(items)}건 -> {OUT}")


if __name__ == "__main__":
    main()
