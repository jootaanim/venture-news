"""출자사업 공고문 첨부파일(PDF·한글 hwp/hwpx·워드 docx/doc)에서 접수마감·심사·선정발표 일정을 뽑아 data/events.json에 저장한다.

원칙
- 공고문에 날짜(연·월·일)가 적혀 있을 때만 기록한다. "12월 중"처럼 일이 없으면 추정하지 않고 비워 둔다(미정).
- 날짜마다 근거 문장(evidence)과 파일명을 같이 남긴다.
- robots.txt와 Crawl-delay를 지키고, 정직한 User-Agent를 쓰며, 인증서 검증을 끄지 않는다.
- 한국벤처투자는 robots.txt가 첨부 다운로드 경로를 막고 서버도 직접 다운로드를 거절하므로 받지 않는다.
- PDF 원문은 저장하지 않고, 추출한 일정과 짧은 근거 문장만 저장한다.

공고문의 일정은 두 가지 모양으로 적힌다.
  A) "접수일시 ◦ 2026년 10월 1일 (목) 16:00까지"      (항목 → 날짜)
  B) "'26.12.02(수) 제안서 접수 10:00~16:00"          (일정표: 날짜 → 내용)
두 모양을 모두 읽고, 같은 종류의 일정은 문서에서 가장 먼저 나온 것 하나만 쓴다.
"""
import argparse
import io
import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import struct
import zipfile
import zlib

import olefile
import requests
from pypdf import PdfReader

from cabundle import ca_bundle

CA = ca_bundle()  # 중간 인증서를 빠뜨린 서버(수출입은행·신한벤처투자)도 검증을 켠 채 접속

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "events.json"
CACHE = ROOT / ".cache" / "pdf_text"
UA = "venture-news-bot/0.1"
SKIP_HOSTS = {
    "www.kvic.or.kr": "robots.txt가 첨부 다운로드 경로를 막고 서버도 직접 다운로드를 거절함",
    "www.kpasset.go.kr": "구형 암호화 방식 허용 여부가 정해지지 않음",
}
TARGET_CATEGORIES = {"출자계획", "선정공고"}
DOC_EXT = (".pdf", ".hwp", ".hwpx", ".docx", ".doc")  # 공고문으로 읽는 첨부파일 종류(PDF·한글·워드)
def bare_name(name):
    """'공고문.pdf (76 KB)'처럼 뒤에 붙은 파일 크기 표기를 떼어 낸 파일 이름."""
    return re.sub(r"\s*\(\s*[\d.,]+\s*[KMG]?B\s*\)\s*$", "", name, flags=re.I)


SKIP_NAME = re.compile(r"서식|양식|매뉴얼|신청서|제출서류|질의|FAQ|안내문|동의서", re.I)

DATE_FULL = re.compile(r"(20\d\d)\s*[.\-년]\s*(\d{1,2})\s*[.\-월]\s*(\d{1,2})\s*일?")
DATE_APOS = re.compile(r"[‘’'ʼ´`]\s?(\d{2})\s*[.\-]\s*(\d{1,2})\s*[.\-]\s*(\d{1,2})")  # '26.12.02
DATE_SHORT = re.compile(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일")

# 종류별 키워드. 접수는 '제안서 접수', '접수일시'처럼 일정을 가리키는 말만 인정한다.
KINDS = {
    # 공고문마다 '접수일시', '접수일', '접수기간', '접수마감'처럼 표기가 달라서 모두 접수마감 일정으로 본다.
    # 단, '제안서 접수일 현재'처럼 기준일을 뜻하는 말은 일정이 아니다.
    "접수마감": re.compile(r"((제안서|서류)\s*)?(접수|제출)\s*(일시|일자|일정|기간|마감|기한|일)(?!\s*(현재|기준))|접수\s*마감|제안서\s*(접수|제출)(?!처|방법)"),
    "서류심사": re.compile(r"서류\s*(심사|평가)"),
    "PT심사": re.compile(r"(PT|P\.T|구술|발표)\s*(심사|평가)|현장\s*실사|면접\s*(심사|평가)"),
    "선정발표": re.compile(r"(최종\s*)?선정\s*(결과)?\s*(발표|통보|통지)|결과\s*발표|심사\s*결과\s*발표"),
}
BAD_GAP = re.compile(r"기준|현재|작성|공시|일\s*자|내\s*용|비\s*고|→|[①-⑩]")
FLOW_ARROW = re.compile(r"→")
MAX_GAP_A = 35   # 키워드 뒤 날짜까지 허용 거리
MAX_GAP_B = 18   # 날짜 뒤 키워드까지 허용 거리


def robots_for(url, cache={}):
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base in cache:
        return cache[base]
    rp = RobotFileParser()
    cache[base] = False  # 확인 실패 = 안전하게 받지 않음
    for attempt in range(3):  # 연결을 자주 끊는 서버(수출입은행)가 있어 몇 번 다시 시도한다
        try:
            r = requests.get(base + "/robots.txt", headers={"User-Agent": UA}, timeout=20, verify=CA)
        except requests.RequestException:
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code == 200 and "<html" not in r.text[:300].lower():
            rp.parse(r.text.splitlines())
            cache[base] = rp
        else:
            cache[base] = None  # robots.txt 없음 = 제한 없음
        break
    return cache[base]


def crawl_delay(rp):
    if rp:
        d = rp.crawl_delay(UA)
        if d:
            return float(d)
    return 1.5


def fetch_pdf(item, att, last_hit):
    url = att["url"]
    host = urlparse(url).netloc
    if host in SKIP_HOSTS:
        return None, "skipped", SKIP_HOSTS[host]
    rp = robots_for(url)
    if rp is False:
        return None, "skipped", "robots.txt를 확인하지 못함"
    if rp and not rp.can_fetch(UA, url):
        return None, "skipped", "robots.txt가 이 경로를 막음"
    wait = crawl_delay(rp) - (time.time() - last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.verify = CA
    headers = {"Referer": item["url"]}  # 공지 페이지에서 링크를 누른 것과 같은 정상 흐름
    for attempt in range(2):
        try:
            r = s.get(url, headers=headers, timeout=60)
            last_hit[host] = time.time()
            if doc_kind(r.content):
                return r.content, "ok", ""
            if attempt == 0:  # 세션 쿠키가 필요한 사이트: 공지 페이지를 먼저 열고 한 번만 다시 시도
                time.sleep(crawl_delay(rp))
                s.get(item["url"], timeout=30)
                last_hit[host] = time.time()
        except requests.RequestException as e:
            return None, "download_failed", type(e).__name__
    return None, "download_failed", "문서가 아닌 응답(접근 거절 가능성)"


def doc_kind(b):
    """내려받은 내용이 PDF / HWP(한글 5.x) / HWPX 중 무엇인지 파일 머리말로 판별한다. 아니면 None."""
    if b[:4] == b"%PDF":
        return "pdf"
    if b[:8] == bytes.fromhex("D0CF11E0A1B11AE1"):
        try:
            ole = olefile.OleFileIO(io.BytesIO(b))
        except Exception:
            return None
        if ole.exists("FileHeader"):
            return "hwp"
        if ole.exists("WordDocument"):
            return "doc"
        return None
    if b[:2] == b"PK":
        try:
            names = zipfile.ZipFile(io.BytesIO(b)).namelist()
        except zipfile.BadZipFile:
            return None
        if any(n.startswith("Contents/") for n in names):
            return "hwpx"
        if "word/document.xml" in names:
            return "docx"
        return None
    return None


def pdf_text(data):
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages), len(reader.pages)


def hwp_text(data):
    """한글(.hwp, 5.x) 본문 글자를 뽑는다. 암호가 걸린 문서는 읽지 않는다."""
    ole = olefile.OleFileIO(io.BytesIO(data))
    header = ole.openstream("FileHeader").read()
    flags = struct.unpack("<I", header[36:40])[0]
    if flags & 2:
        raise ValueError("암호화된 문서")
    compressed = bool(flags & 1)
    sections = sorted(
        ("/".join(p) for p in ole.listdir() if len(p) == 2 and p[0] == "BodyText" and p[1].startswith("Section")),
        key=lambda s: int(re.sub(r"\D", "", s) or 0),
    )
    out = []
    for sec in sections:
        raw = ole.openstream(sec).read()
        if compressed:
            raw = zlib.decompress(raw, -15)
        pos = 0
        while pos + 4 <= len(raw):
            h = struct.unpack("<I", raw[pos: pos + 4])[0]
            tag, size = h & 0x3FF, (h >> 20) & 0xFFF
            pos += 4
            if size == 0xFFF:
                size = struct.unpack("<I", raw[pos: pos + 4])[0]
                pos += 4
            payload = raw[pos: pos + size]
            pos += size
            if tag != 67:  # HWPTAG_PARA_TEXT
                continue
            s, i = [], 0
            while i + 1 < len(payload):
                ch = struct.unpack("<H", payload[i: i + 2])[0]
                if ch in (10, 13):
                    s.append("\n"); i += 2
                elif ch < 32 and ch not in (0, 24, 25, 26, 27, 28, 29, 30, 31):
                    i += 16  # 표·그림 등 확장 컨트롤은 8글자(16바이트)를 차지한다
                elif ch < 32:
                    i += 2
                else:
                    s.append(chr(ch)); i += 2
            out.append("".join(s))
    return "\n".join(out), None


def hwpx_text(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    parts = sorted(n for n in z.namelist() if re.match(r"Contents/section\d+\.xml", n))
    txt = []
    for n in parts:
        xml = z.read(n).decode("utf-8", "replace")
        txt.append(re.sub(r"<[^>]+>", " ", re.sub(r"</hp:p>", "\n", xml)))
    return "\n".join(txt), None


def docx_text(data):
    """워드(.docx) 본문 글자. 문단(</w:p>)과 표 칸(</w:tc>)마다 줄을 바꾼다."""
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"</w:p>|</w:tc>", "\n", xml)
    xml = re.sub(r"<w:tab/>", " ", xml)
    return re.sub(r"<[^>]+>", "", xml), None


def word97_text(data):
    """옛 워드(.doc) 본문 글자. 정확한 구조 해석 대신 본문 스트림에서 UTF-16 글자 덩어리를 모은다."""
    ole = olefile.OleFileIO(io.BytesIO(data))
    raw = ole.openstream("WordDocument").read()
    runs = re.findall(r"(?:[\x20-\x7e·‘-”　-〿가-힣！-～\r\n\t]){4,}",
                      raw.decode("utf-16le", "ignore"))
    return "\n".join(runs).replace("\r", "\n"), None


def doc_text(data):
    kind = doc_kind(data)
    if kind == "docx":
        return docx_text(data)
    if kind == "doc":
        return word97_text(data)
    if kind == "pdf":
        return pdf_text(data)
    if kind == "hwp":
        return hwp_text(data)
    if kind == "hwpx":
        return hwpx_text(data)
    raise ValueError("지원하지 않는 문서")


def find_dates(flat, published):
    """문서 전체에서 날짜를 위치 순으로 찾는다. [(date, start, end)]"""
    pub = datetime.strptime(published, "%Y-%m-%d").date()
    found, spans = [], []

    def add(y, mo, d, m):
        try:
            found.append((date(y, mo, d), m.start(), m.end()))
            spans.append((m.start(), m.end()))
        except ValueError:
            pass

    for m in DATE_FULL.finditer(flat):
        add(int(m.group(1)), int(m.group(2)), int(m.group(3)), m)
    for m in DATE_APOS.finditer(flat):
        if not any(a <= m.start() < b or a < m.end() <= b for a, b in spans):
            add(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)), m)
    for m in DATE_SHORT.finditer(flat):
        if any(a <= m.start() < b for a, b in spans):
            continue
        y, mo, d = pub.year, int(m.group(1)), int(m.group(2))
        try:
            dt = date(y, mo, d)
            if dt < pub - timedelta(days=30):
                dt = date(y + 1, mo, d)
            add(dt.year, dt.month, dt.day, m)
        except ValueError:
            pass
    found.sort(key=lambda x: x[1])
    return found


def extract_events(text, published):
    pub = datetime.strptime(published, "%Y-%m-%d").date()
    flat = re.sub(r"\s+", " ", text)
    # 일정은 공고일 이후여야 한다. 공고일 이전 날짜는 작성기준일 등 다른 날짜다.
    dates = [d for d in find_dates(flat, published) if pub <= d[0] <= pub + timedelta(days=365)]
    cands = {k: [] for k in KINDS}  # 종류 -> [(위치, 날짜, 근거)]

    for kind, rx in KINDS.items():
        for m in rx.finditer(flat):
            # 선정 절차를 나열한 화살표 문장(공고→접수→심사→…)은 일정이 아니다.
            near = flat[max(0, m.start() - 3): m.end() + 3]
            if FLOW_ARROW.search(near):
                continue
            # A) 키워드 뒤에 날짜
            for dt, s, e in dates:
                if s < m.end():
                    continue
                gap = flat[m.end(): s]
                if len(gap) > MAX_GAP_A:
                    break
                if BAD_GAP.search(gap):
                    break
                end = (dt, s, e)
                # 범위(~)면 뒤쪽 날짜가 마감
                nxt = next((x for x in dates if x[1] > e), None)
                if nxt and re.fullmatch(r"[^0-9]{0,24}?[~∼～\-–—][^0-9]{0,6}", flat[e: nxt[1]]):
                    end = nxt
                cands[kind].append((m.start(), end[0], flat[m.start(): end[2]]))
                break
        # B) 날짜 뒤에 키워드(일정표 한 줄)
        for idx, (dt, s, e) in enumerate(dates):
            seg = flat[e: e + MAX_GAP_B + 25]
            km = rx.search(seg)
            if not km or km.start() > MAX_GAP_B:
                continue
            gap = seg[: km.start()]
            if BAD_GAP.search(gap) or re.search(r"20\d\d|[‘’'`]\s?\d{2}\s*\.", gap):
                continue  # 사이에 다른 날짜가 끼면 그 날짜의 내용이다
            if FLOW_ARROW.search(flat[max(0, e - 3): e + km.end() + 3]):
                continue
            cands[kind].append((s, dt, flat[s: e + km.end()]))

    events = []
    for kind, lst in cands.items():
        if not lst:
            continue
        lst.sort(key=lambda x: x[0])
        pos, dt, ev = lst[0]
        events.append({"type": kind, "date": dt.isoformat(), "evidence": ev.strip()[:110]})
    # 심사·발표는 접수마감보다 뒤여야 한다. 같은 날이거나 앞서면 표 머리글을 잘못 읽은 것이다.
    due = next((e["date"] for e in events if e["type"] == "접수마감"), None)
    if due:
        events = [e for e in events if e["type"] == "접수마감" or e["date"] > due]
    return events


def load():
    return json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}


def save(records):
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")


RANK = {"ok": 3, "no_date": 2, "no_text": 1}


def read_one(cache_key, it, att, last_hit):
    """첨부파일 하나를 받아(또는 캐시에서) 일정을 뽑은 기록을 돌려준다."""
    # 다시 읽을 때 같은 파일을 또 받지 않도록 글자만 로컬에 캐시한다(.cache는 저장소에 올리지 않는다).
    cfile = CACHE / (re.sub(r"[^0-9A-Za-z가-힣_-]", "_", cache_key) + ".txt")
    cached = cfile.read_text(encoding="utf-8") if cfile.exists() else None
    if cached is not None:
        data, status, note = b"cached", "ok", ""
    else:
        data, status, note = fetch_pdf(it, att, last_hit)
    rec = {"source": it["source"], "title": it["title"], "url": it["url"], "published": it["published"],
           "file": att["name"], "status": status, "note": note, "events": [], "tried": str(date.today())}
    if data:
        try:
            if cached is not None:
                text, pages = cached, None
            else:
                text, pages = doc_text(data)
                CACHE.mkdir(parents=True, exist_ok=True)
                cfile.write_text(text, encoding="utf-8")
            rec["pages"] = pages
            if len(text.strip()) < 50:
                rec["status"], rec["note"] = "no_text", "텍스트가 없는 문서(스캔본 가능성)"
            else:
                rec["events"] = extract_events(text, it["published"])
                rec["status"] = "ok" if rec["events"] else "no_date"
        except Exception as e:
            rec["status"], rec["note"] = "parse_failed", type(e).__name__
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=str(date.today() - timedelta(days=183)))
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--retry-days", type=int, default=3, help="다운로드 실패 건을 다시 시도하기까지의 일수")
    ap.add_argument("--redo", action="store_true", help="이미 처리한 공고도 다시 처리")
    ap.add_argument("--redo-status", default="", help="이 상태(쉼표로 여러 개)로 기록된 공고만 다시 처리. 예: no_date,parse_failed")
    ap.add_argument("--skip-source", default="", help="이번에 건너뛸 기관(쉼표로 여러 개)")
    args = ap.parse_args()

    records = load()
    todo = []
    for f in sorted((ROOT / "data").glob("*.json")):
        if f.name == "events.json":
            continue
        for it in json.loads(f.read_text(encoding="utf-8")):
            if it.get("kind") != "notice" or it["category"] not in TARGET_CATEGORIES or it["published"] < args.since:
                continue
            key = f'{it["source"]}-{it["id"]}'
            old = records.get(key)
            if it["source"] in set(filter(None, args.skip_source.split(","))):
                continue
            redo_this = args.redo or (old and old["status"] in set(filter(None, args.redo_status.split(","))))
            if old and not redo_this and old["status"] != "download_failed":
                continue
            if old and old["status"] == "download_failed" and old.get("tried", "") > str(date.today() - timedelta(days=args.retry_days)):
                continue
            pdfs = [a for a in it.get("attachments", []) if a.get("url") and bare_name(a["name"]).lower().endswith(DOC_EXT) and not SKIP_NAME.search(a["name"])]
            if not pdfs:
                records[key] = {"source": it["source"], "title": it["title"], "url": it["url"], "published": it["published"],
                                "status": "no_pdf", "events": [], "tried": str(date.today())}
                continue
            # 공고문 이름이 들어간 파일을 먼저, 같은 조건이면 PDF를 한글 파일보다 먼저 쓴다.
            pdfs.sort(key=lambda a: (0 if re.search(r"공고|계획", a["name"]) else 1, 0 if bare_name(a["name"]).lower().endswith(".pdf") else 1))
            todo.append((key, it, pdfs[:3]))  # 첫 파일에 날짜가 없으면 다음 파일(최대 3개)도 읽는다

    todo.sort(key=lambda t: t[1]["published"], reverse=True)
    todo = todo[: args.limit]
    print(f"대상 {len(todo)}건")
    last_hit = {}
    for key, it, atts in todo:
        rec = None
        for n, att in enumerate(atts):
            r = read_one(key if n == 0 else f"{key}__{n}", it, att, last_hit)
            # 날짜를 찾은 파일, 아니면 가장 진척된 결과를 남긴다(ok > no_date > 그 외)
            if rec is None or RANK.get(r["status"], 0) > RANK.get(rec["status"], 0):
                rec = r
            if r["status"] == "ok":
                break
        records[key] = rec
        print(f"[{rec['status']}] {it['source']} {it['published']} {it['title'][:36]} -> {[(e['type'], e['date']) for e in rec['events']]} {rec['note']}")
        save(records)
    save(records)
    print(f"완료: 전체 {len(records)}건 기록 -> {OUT}")


if __name__ == "__main__":
    main()
