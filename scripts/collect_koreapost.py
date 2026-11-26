"""우정사업본부 출자사업(위탁운용사 선정) 공고 수집기.

게시판: 우정사업본부 자산운용시스템(kpasset.go.kr) > 공지사항 > 거래기관 선정공고
  - 예금: https://www.kpasset.go.kr/board.es?mid=a10510000000&bid=0041
  - 보험: https://www.kpasset.go.kr/board.es?mid=a10510000000&bid=0042
- robots.txt: https://www.kpasset.go.kr/robots.txt 는 404(제한 규칙 없음). Crawl-delay 없음.
  (www.koreapost.go.kr/robots.txt 는 Googlebot에 /*bbs* 를 막지만 이 수집기는 해당 사이트를 쓰지 않는다.)
- 서버가 구형 TLS 암호군(AES128-SHA)만 허용해 기본 설정으론 핸드셰이크가 실패한다.
  인증서 검증은 그대로 켜 두고 암호군만 'DEFAULT@SECLEVEL=0'으로 낮춘다.
- 기본 수집 기간: 최근 183일(--since로 변경). 이미 저장한 id를 만나면 게시판별로 증분 종료.
"""
import argparse
import json
import re
import ssl
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote, unquote

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

BASE = "https://www.kpasset.go.kr"
MID = "a10510000000"
BOARDS = {"0041": "예금", "0042": "보험"}
OUT = Path(__file__).resolve().parent.parent / "data" / "koreapost.json"
UA = "MoheomJabonNewsBot/1.0 (venture-news research collector; polite 1 req/s)"
DELAY = 1.0
KEYWORDS = ["출자", "위탁운용", "운용사", "VC", "벤처", "펀드", "GP", "PEF", "선정"]


class LegacyTLS(HTTPAdapter):
    def init_poolmanager(self, *a, **k):
        ctx = ssl.create_default_context()  # 인증서 검증 유지
        ctx.set_ciphers("DEFAULT@SECLEVEL=0")
        k["ssl_context"] = ctx
        super().init_poolmanager(*a, **k)


S = requests.Session()
S.mount("https://", LegacyTLS())
S.headers["User-Agent"] = UA
_last = [0.0]


def get(url):
    for attempt in range(3):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            r = S.get(url, timeout=30)
            _last[0] = time.time()
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            _last[0] = time.time()
            print(f"  요청 실패({attempt + 1}/3): {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"요청 3회 실패: {url}")


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def relevant(title):
    t = title.upper()
    return any(k.upper() in t for k in KEYWORDS)


def categorize(title):
    if "접수" in title:
        return "접수현황"
    if any(k in title for k in ["정량평가", "서류", "1차", "2차", "정성평가"]):
        return "서류결과"
    if any(k in title for k in ["우선협상", "예비", "선정 결과", "선정결과", "선정 안내", "결과"]):
        return "선정결과"
    if any(k in title for k in ["공고", "선정계획", "공모"]):
        return "출자계획"
    return "기타"


def list_url(bid, page):
    return f"{BASE}/board.es?mid={MID}&bid={bid}&nPage={page}"


def view_url(bid, no):
    return f"{BASE}/board.es?mid={MID}&bid={bid}&bid2=&bid3=&act=view&list_no={no}&tag=&nPage=1"


def parse_list(html):
    rows = []
    for tr in BeautifulSoup(html, "html.parser").select("table.tstyle_list tbody tr"):
        a, d = tr.select_one("td.title a"), tr.select_one("td.date")
        m = re.search(r"list_no=(\d+)", a["href"]) if a else None
        if not (a and d and m):
            continue
        rows.append({"no": m.group(1), "title": clean(a.get("title") or a.text), "date": d.text.strip()[:10]})
    return rows


def parse_detail(html):
    b = BeautifulSoup(html, "html.parser")
    c = b.select_one("td.tb_contents")
    body = ""
    if c:
        for br in c.find_all("br"):
            br.replace_with("\n")
        body = re.sub(r"\n{3,}", "\n\n", "\n".join(clean(x) for x in c.get_text().split("\n"))).strip()
    att = []
    for a in b.select("tr.add_file a[href*='download.es']"):
        href = a["href"].replace("&amp;", "&")
        name = clean(unquote(re.search(r"filenameOrg=([^&]*)", href).group(1))) if "filenameOrg=" in href else clean(a.text)
        att.append({"name": name, "url": BASE + quote(href, safe="/?&=:%")})
    return body, att


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=(date.today() - timedelta(days=183)).isoformat())
    a = ap.parse_args()
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    known = {r["id"] for r in old}
    new = []
    for bid, label in BOARDS.items():
        page, stop = 1, False
        while not stop:
            rows = parse_list(get(list_url(bid, page)))
            if not rows:
                break
            for r in rows:
                rid = f"koreapost-{bid}-{r['no']}"
                if r["date"] < a.since:
                    stop = True
                    break
                if rid in known:
                    stop = True
                    break
                if not relevant(r["title"]):
                    continue
                body, att = parse_detail(get(view_url(bid, r["no"])))
                new.append({"id": rid, "source": "우정사업본부", "kind": "notice",
                            "category": categorize(r["title"]), "title": r["title"],
                            "published": r["date"], "url": view_url(bid, r["no"]),
                            "attachments": att, "body": body})
            page += 1
    allr = sorted(new + old, key=lambda x: (x["published"], x["id"]), reverse=True)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(allr, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"신규 {len(new)}건 / 전체 {len(allr)}건 (since {a.since})")


if __name__ == "__main__":
    main()
