"""data/kvic.json + site/template.html -> site/index.html (데이터가 안에 들어간 단일 파일).

데이터를 HTML 안에 넣어서, 파일을 더블클릭해 열거나 패널 미리보기로 열어도 데이터가 보인다.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 기관마다 카테고리 이름이 달라서 화면용 공통 카테고리로 맞춘다.
MAIN = {"출자계획", "선정결과", "접수현황", "서류결과", "질의응답"}
ALIAS = {"선정공고": "출자계획"}  # 한국성장금융 '선정공고' = 위탁운용사 선정계획 공고


def norm_cat(cat):
    cat = ALIAS.get(cat, cat)
    return cat if cat in MAIN else "기타"


items = []
for f in sorted((ROOT / "data").glob("*.json")):
    items += json.loads(f.read_text(encoding="utf-8"))

slim = [
    {
        "id": f'{it["source"]}-{it["id"]}',
        "src": it["source"],
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
