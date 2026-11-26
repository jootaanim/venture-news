"""신한벤처투자 출자사업(신한벤처 넥서스 모펀드 등) 공고 수집기.

- 게시판: https://www.shinhanvc.com/kr/notice/notice (robots.txt는 특정 봇만 언급, 일반 봇 제한 없음)
- 상세: https://www.shinhanvc.com/kr/notice/notice/{번호}
- 게시판에는 재무제표 공시 등 무관한 글도 있어 제목 키워드로 출자 관련만 남긴다.
- 기본 수집 기간: 최근 6개월(--since). 이미 저장한 번호는 건너뛴다.
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

BASE = "https://www.shinhanvc.com"
BOARD = "/kr/notice/notice"
OUT = Path(__file__).resolve().parent.parent / "data" / "shinhanvc.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; venture-news-bot/0.1)"}
DELAY = 1.0
KEYWORDS = ("출자", "위탁운용", "모펀드", "운용사 선정", "GP")


def _ca_bundle():
    """이 사이트는 중간 인증서를 빼고 내려준다. 발급기관(Sectigo)의 공식 중간 인증서를 기본 신뢰 목록에 더해
    검증은 그대로 켠 채 접속한다(certs/sectigo_rsa_dv_intermediate.pem)."""
    import certifi
    extra = Path(__file__).resolve().parent.parent / "certs" / "sectigo_rsa_dv_intermediate.pem"
    out = Path(__file__).resolve().parent.parent / ".cache" / "ca_bundle.pem"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(Path(certifi.where()).read_text() + "\n" + extra.read_text())
    return str(out)


CA = _ca_bundle()


def get(path, **params):
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE}{path}", params=params, headers=HEADERS, timeout=30, verify=CA)
            r.raise_for_status()
            return r.content.decode("utf-8", errors="replace")
        except requests.RequestException as e:
            print(f"  요청 실패({attempt + 1}/3): {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"요청 3회 실패: {path} {params}")


def clean(s):
    return re.sub(r"\s+", " ", s.replace("​", "")).strip()


def classify(title):
    if "질의" in title or "FAQ" in title:
        return "질의응답"
    if "접수" in title:
        return "접수현황"
    if "최종" in title and "결과" in title:
        return "선정결과"
    if ("심사" in title or "서류" in title) and "결과" in title:
        return "서류결과"
    if "선정" in title and "결과" in title:
        return "선정결과"
    if any(k in title for k in ("계획", "공고", "설명회", "모집", "공모")):
        return "출자계획"
    return "기타"


def parse_list(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for a in soup.select("div.notibody > a[href]"):
        m = re.search(r"/notice/notice/(\d+)", a["href"])
        t = a.select_one("div.inner")
        cells = a.select("div.noticell")
        if not (m and t and cells):
            continue
        rows.append({"id": int(m.group(1)), "title": clean(t.get_text()),
                     "published": cells[-1].get_text(strip=True)})
    return rows


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    files = []
    for a in soup.select("a[href]"):
        h = a["href"]
        if re.search(r"download|file", h, re.I) and not h.startswith("javascript"):
            files.append({"name": clean(a.get_text()) or "첨부파일", "url": h if h.startswith("http") else f"{BASE}{h}"})
    node = soup.select_one("div.view, div.notice-view, div.content, article")
    return {"attachments": files, "body": node.get_text("\n", strip=True) if node else ""}


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
    ap.add_argument("--max-pages", type=int, default=10)
    args = ap.parse_args()

    items = load()
    known = set(items)
    new_count = 0
    for page in range(1, args.max_pages + 1):
        rows = parse_list(get(BOARD, page=page - 1))  # 이 게시판의 page는 0부터 시작(0이 최신)
        if not rows:
            break
        fresh = [r for r in rows if r["id"] not in known]
        pick = [r for r in fresh if r["published"] >= args.since and any(k in r["title"] for k in KEYWORDS)]
        print(f"{page}페이지: {len(rows)}건 중 신규 {len(fresh)}건, 기간 내 관련 {len(pick)}건")
        for r in pick:
            time.sleep(DELAY)
            d = parse_detail(get(f"{BOARD}/{r['id']}"))
            items[r["id"]] = {"id": r["id"], "source": "신한벤처투자", "kind": "notice",
                              "category": classify(r["title"]), "title": r["title"],
                              "published": r["published"], "url": f"{BASE}{BOARD}/{r['id']}", **d}
            new_count += 1
        if len(fresh) < len(rows) or all(r["published"] < args.since for r in rows):
            break
        time.sleep(DELAY)
    save(items)
    print(f"완료: 신규 {new_count}건, 전체 {len(items)}건 -> {OUT}")


if __name__ == "__main__":
    main()
