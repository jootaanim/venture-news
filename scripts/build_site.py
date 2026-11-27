"""data/kvic.json + site/template.html -> site/index.html (데이터가 안에 들어간 단일 파일).

데이터를 HTML 안에 넣어서, 파일을 더블클릭해 열거나 패널 미리보기로 열어도 데이터가 보인다.
"""
import json
from datetime import datetime, timedelta, timezone
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 기관마다 카테고리 이름이 달라서 화면용 공통 카테고리로 맞춘다.
MAIN = {"출자계획", "선정결과", "접수현황", "서류결과", "질의응답"}
ALIAS = {"선정공고": "출자계획"}  # 한국성장금융 '선정공고' = 위탁운용사 선정계획 공고


NEWS_CATS = {"VC·펀드", "출자·LP", "벤처기업"}
PRIORITY_OUTLETS = {"더벨", "딜사이트"}
OUTLET_ALIAS = {"thebell Free": "더벨", "THE BELL": "더벨"}


# 기관이 붙인 분류와 제목이 어긋나는 경우(예: 한국성장금융은 "서류심사 결과" 글에도 【선정결과】를 붙인다)는
# 제목을 우선한다. 제목에 "서류심사 결과"가 있으면 최종 선정이나 출자계획이 아니라 서류결과다.
DOC_RESULT = re.compile(r"서류\s*심사\s*(결과|발표)|서류\s*결과")
TITLE_RULES = [
    (DOC_RESULT, "서류결과"),
    (re.compile(r"접수\s*(현황|결과)"), "접수현황"),
    (re.compile(r"질의\s*응답"), "질의응답"),
]


def norm_cat(cat, title=""):
    cat = ALIAS.get(cat, cat)
    # 기관이 넓은 분류(출자계획·선정결과·기타)로 올렸더라도 제목에 분명한 표현이 있으면 그 종류로 본다.
    if cat in ("출자계획", "선정결과", "기타"):
        for rx, to in TITLE_RULES:
            if rx.search(title):
                return to
    return cat if cat in MAIN or cat in NEWS_CATS else "기타"


items = []
for f in sorted((ROOT / "data").glob("*.json")):
    if f.name == "events.json":  # 공고문 PDF에서 뽑은 일정은 따로 읽는다
        continue
    if f.name == "koreapost.json":  # 우정사업본부는 자동 수집을 하지 않고 안내 링크만 둔다(사이트에 싣지 않음)
        continue
    items += json.loads(f.read_text(encoding="utf-8"))

# 연기금·공제회·우정사업본부 게시판에는 해외주식, 부동산, PEF 등 벤처캐피탈과 무관한 공고도 섞여 있어
# 국내 VC 대상 공고만 남긴다. (제목에 VC·벤처가 있고, 제외 키워드가 없는 글)
MIXED_BOARDS = {"우정사업본부", "군인공제회", "교직원공제회", "국민연금"}
KEEP = re.compile(r"VC|벤처")
DROP = re.compile(r"해외|주식|채권|부동산|헤지|인프라")


# 뉴스는 키워드 검색 결과라 무관한 기사가 섞인다. 제목에 투자·벤처 관련 단어가 있는 기사만 남긴다.
NEWS_KEEP = re.compile(
    r"벤처|VC|펀드|투자|스타트업|창업|출자|IPO|상장|시리즈|유치|LP|GP|운용사|캐피탈|캐피털|모태|성장금융|인수|M&A|엑시트|딥테크|세컨더리",
    re.I,
)


def relevant(it):
    if it.get("kind") == "article":
        return bool(NEWS_KEEP.search(it["title"]))
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

# 다른 기관이 대신 공고하는 출자사업을 실제 출자자 버튼에도 보이게 하는 규칙(예: ("기업은행", re.compile(r"IBK"))).
# 지금은 비워 둔다: '기은' 버튼은 기업은행이 직접 올린 공고(collect_ibk.py)만 보여 준다(운영자 요청, 2026-11-27).
FUNDER_RULES = []


def funders(it):
    if it.get("kind", "notice") != "notice":
        return []
    return [name for name, rx in FUNDER_RULES if name != it["source"] and rx.search(it["title"])]


from kdb_url import detail_url  # 산업은행은 글 상세 주소를 계산해서 쓴다(scripts/kdb_url.py)


def pick_url(it):
    if it["source"] == "산업은행":
        return detail_url(it["id"])
    return it["url"]


slim = [
    {
        "id": f'{it["source"]}-{it["id"]}',
        "src": it["source"],
        "kind": it.get("kind", "notice"),
        "pub": OUTLET_ALIAS.get(it.get("outlet", ""), it.get("outlet", "")),
        "pri": 1 if OUTLET_ALIAS.get(it.get("outlet", ""), it.get("outlet", "")) in PRIORITY_OUTLETS else 0,
        "cat": norm_cat(it["category"], it["title"]),
        "title": " ".join(it["title"].split()),
        "date": it["published"],
        "url": pick_url(it),
        "files": len(it.get("attachments", [])),
        "also": funders(it),
    }
    for it in items
]
# 최신순, 같은 날짜 안에서는 최우선 매체(더벨·딜사이트) 기사를 먼저 둔다.
slim.sort(key=lambda x: (x["date"], x["pri"], x["id"]), reverse=True)

tpl = (ROOT / "site" / "template.html").read_text(encoding="utf-8")
tag = '<script src="data.js"></script>'
assert tag in tpl, "template.html에 data.js 자리표시가 없습니다"
# </ 가 들어간 제목이 script를 끊지 않도록 이스케이프
payload = json.dumps(slim, ensure_ascii=False).replace("</", "<\\/")

# 공고문 PDF에서 추출한 일정. 사이트에 올라가는 공고(필터 통과)에 속한 일정만 쓴다.
EVENT_TYPES = {"접수마감", "서류심사", "PT심사", "선정발표"}
link_of = {f'{it["source"]}-{it["id"]}': pick_url(it) for it in items if it.get("kind") == "notice"}
kept = {f'{it["source"]}-{it["id"]}' for it in items if it.get("kind") == "notice"}
events = []
ev_file = ROOT / "data" / "events.json"
if ev_file.exists():
    for key, rec in json.loads(ev_file.read_text(encoding="utf-8")).items():
        if key not in kept or rec.get("status") != "ok":
            continue
        # 이미 저장된 추출 결과에도 같은 검증을 적용한다: 심사·발표는 접수마감보다 뒤여야 한다.
        due = next((e["date"] for e in rec["events"] if e["type"] == "접수마감"), None)
        for e in rec["events"]:
            if due and e["type"] != "접수마감" and e["date"] <= due:
                continue
            if e["type"] in EVENT_TYPES:
                events.append({
                    "d": e["date"], "t": e["type"], "src": rec["source"],
                    "title": " ".join(rec["title"].split()), "url": link_of.get(key, rec["url"]),
                    "also": [n for n, rx in FUNDER_RULES if rx.search(rec["title"])],
                    "ev": " ".join(e["evidence"].split()), "file": rec.get("file", ""),
                })
events.sort(key=lambda x: (x["d"], x["t"]))
ev_payload = json.dumps(events, ensure_ascii=False).replace("</", "<\\/")
# 사이트를 만든 시각(한국 시간). 서버(GitHub)는 UTC라서 시간대를 명시한다.
KST = timezone(timedelta(hours=9))
built = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
html = tpl.replace(tag, f'<script>window.DATA={payload};window.EVENTS={ev_payload};window.BUILT="{built}";</script>')

out = ROOT / "site" / "index.html"
out.write_text(html, encoding="utf-8")
print(f"{len(slim)}건, 일정 {len(events)}건 -> {out}")
