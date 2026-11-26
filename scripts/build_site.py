"""data/kvic.json + site/template.html -> site/index.html (데이터가 안에 들어간 단일 파일).

데이터를 HTML 안에 넣어서, 파일을 더블클릭해 열거나 패널 미리보기로 열어도 데이터가 보인다.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 기관마다 카테고리 이름이 달라서 화면용 공통 카테고리로 맞춘다.
MAIN = {"출자계획", "선정결과", "접수현황", "서류결과", "질의응답"}
ALIAS = {"선정공고": "출자계획"}  # 한국성장금융 '선정공고' = 위탁운용사 선정계획 공고


NEWS_CATS = {"VC·펀드", "출자·LP", "벤처기업"}


def norm_cat(cat):
    cat = ALIAS.get(cat, cat)
    return cat if cat in MAIN or cat in NEWS_CATS else "기타"


items = []
for f in sorted((ROOT / "data").glob("*.json")):
    items += json.loads(f.read_text(encoding="utf-8"))

# 연기금·공제회·우정사업본부 게시판에는 해외주식, 부동산, PEF 등 벤처캐피탈과 무관한 공고도 섞여 있어
# 국내 VC 대상 공고만 남긴다. (제목에 VC·벤처가 있고, 제외 키워드가 없는 글)
MIXED_BOARDS = {"우정사업본부", "군인공제회", "교직원공제회", "국민연금"}
KEEP = re.compile(r"VC|벤처")
DROP = re.compile(r"해외|주식|채권|부동산|헤지|인프라")


def relevant(it):
    if it["source"] not in MIXED_BOARDS:
        return True
    return bool(KEEP.search(it["title"])) and not DROP.search(it["title"])


items = [it for it in items if relevant(it)]

# 우정사업본부처럼 같은 공고를 날짜만 바꿔 다시 올리는 게시판은 가장 최근 것 하나만 둔다.
# (한국벤처투자·한국성장금융 등은 같은 제목의 별개 공지가 있을 수 있어 그대로 둔다.)
seen, deduped = set(), []
for it in sorted(items, key=lambda x: x["published"], reverse=True):
    key = (it["source"], " ".join(it["title"].split()))
    if it["source"] in MIXED_BOARDS and key in seen:
        continue
    seen.add(key)
    deduped.append(it)
items = deduped

slim = [
    {
        "id": f'{it["source"]}-{it["id"]}',
        "src": it["source"],
        "kind": it.get("kind", "notice"),
        "pub": it.get("outlet", ""),
        "cat": norm_cat(it["category"]),
        "title": " ".join(it["title"].split()),
        "date": it["published"],
        "url": it["url"],
        "files": len(it.get("attachments", [])),
    }
    for it in items
]
slim.sort(key=lambda x: (x["date"], x["id"]), reverse=True)

tpl = (ROOT / "site" / "template.html").read_text(encoding="utf-8")
tag = '<script src="data.js"></script>'
assert tag in tpl, "template.html에 data.js 자리표시가 없습니다"
# </ 가 들어간 제목이 script를 끊지 않도록 이스케이프
payload = json.dumps(slim, ensure_ascii=False).replace("</", "<\\/")
html = tpl.replace(tag, f"<script>window.DATA={payload};</script>")

out = ROOT / "site" / "index.html"
out.write_text(html, encoding="utf-8")
print(f"{len(slim)}건 -> {out}")
