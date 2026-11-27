# 모험자본 뉴스 — 작업 안내 (Claude용)

출자기관·LP 담당자를 위해 국내 출자사업(모펀드) 공고와 VC 뉴스를 모아 보여주는 공개 정적 사이트.
- 사이트: https://jootaanim.github.io/venture-news/
- 갱신: GitHub Actions `.github/workflows/collect.yml`가 매시 17분에 수집 → 일정 추출 → 사이트 빌드 → 커밋 → Pages 배포
- 이 문서는 새 세션(다른 계정 포함)이 바로 이어서 작업할 수 있도록 현재 상태와 지켜야 할 규칙을 적어 둔 것이다.

## 폴더
| 위치 | 내용 |
|---|---|
| `scripts/collect_*.py` | 기관별 수집기. 결과는 `data/<이름>.json` |
| `scripts/collect_news.py` | 언론사 RSS 뉴스 → `data/news.json` |
| `scripts/extract_dates.py` | 공고 첨부파일(PDF·HWP·HWPX·DOCX·DOC)에서 접수마감 등 일정 추출 → `data/events.json` |
| `scripts/build_site.py` | `site/template.html`에 자료를 넣어 `site/index.html` 생성 |
| `scripts/backfill.py` | 과거 자료 한꺼번에 채우기(손으로 한 번 돌리는 용도) |
| `scripts/cabundle.py` | certifi + `certs/*.pem` 중간 인증서를 합친 CA 묶음 |
| `scripts/kdb_url.py` | 산업은행 공고 상세 주소(서명값 계산) |
| `certs/` | 서버가 중간 인증서를 안 보내는 기관용 중간 인증서(수출입은행, 신한벤처투자) |
| `site/template.html` | 화면 전체(HTML·CSS·JS 한 파일). 화면 수정은 여기서 |
| `docs/수집허용.md` | robots.txt가 막지만 운영자가 허용 답변을 받은 기관 기록 |
| `docs/설계.md` | 초기 설계 메모(2026-11-25). 일부 내용은 지금과 다름 |
| `mockup/` | 초기 화면 시안 |

## 출자기관과 수집기 (화면 버튼 이름)
| 기관 | 수집기 | 버튼 | 비고 |
|---|---|---|---|
| 한국벤처투자 | kvic | 모태 | 첨부파일은 robots.txt가 막아 일정 추출 안 함 |
| 한국성장금융 | kgrowth | 성장금융 | robots Crawl-Delay 60초 지킴. 오래 걸림 |
| 산업은행 | kdb | 산은 | 상세 주소는 kdb_url.py로 계산 |
| KIF | kif | KIF | |
| 수출입은행 | koreaexim | 수은 | 중간 인증서 certs/thawte_tls_rsa_ca_g1.pem |
| 교직원공제회 | ktcu | 교공 | |
| 군인공제회 | mmaa | 군공 | |
| 국민연금 | nps | 국민연금 | |
| 과학기술인공제회 | sema | 과기공 | 검색어로만 수집. 첨부는 robots가 막음 |
| 기업은행 | ibk | 기은 | 허용 답변으로 수집(docs/수집허용.md). 성장금융 글은 기은 버튼에서 제외 |
| 농업정책보험금융원 | apfs | 농금원 | 허용 답변으로 수집(docs/수집허용.md) |
| 신한자산운용 | shinhanam | 신한자산 | 글 번호를 거꾸로 따라 읽음 |
| 신한벤처투자 | shinhanvc | 신벤 | 중간 인증서 certs/sectigo_*.pem (2027-06 만료 예정) |
| 우리자산운용 | wooriam | 우리자산 | |
| 키움인베스트먼트 | kiwoom | 키움인베 | |
| 우정사업본부 | koreapost | 우정 | 수집하지 않고 안내 링크만(사이트 TLS가 약한 암호만 지원, 사용자 결정) |

추가하지 않은 기관: IBK자산운용, NH벤처투자, NH농협은행, 농협중앙회(공개 출자사업 공고를 찾지 못함).

## 반드시 지킬 규칙
1. **robots.txt와 Crawl-delay를 지킨다.** 예외는 운영자가 허용 답변을 받아 `docs/수집허용.md`에 적은 기관(기업은행, 농금원)뿐이다.
2. **User-Agent를 속이지 않는다.** 항상 `Mozilla/5.0 (compatible; venture-news-bot/0.1)`. 검색엔진 봇 흉내 금지.
3. **인증서 검증을 끄지 않는다**(`verify=False` 금지). 중간 인증서가 빠진 사이트는 `certs/`에 추가하고 `cabundle.py`를 쓴다.
4. **저작권:** 제목 + 원문 링크 + 자체 요약만 노출한다. 본문 전체를 사이트에 싣지 않는다.
5. 일정 날짜를 못 찾으면 추정하지 않는다. "접수마감일·접수일·접수일시·접수기간"은 접수마감으로 본다.
6. 개인정보를 사이트에 올리지 않는다.
7. 새 수집기는 증분 수집(이미 저장한 글을 만나면 멈춤), 기본 기간 6개월(`--since`), 요청 사이 지연, 실패해도 다른 기관은 계속(`continue-on-error`).

## 작업 방법
- 로컬 실행(Windows): `py scripts/collect_<이름>.py`, `py scripts/extract_dates.py`, `py scripts/build_site.py` 후 `site/index.html`을 브라우저로 확인.
- 의존성: `py -m pip install -r requirements.txt`
- 과거 자료 채우기: `py scripts/backfill.py --since 2024-01-01 <수집기 이름>`.
  성장금융은 `py scripts/collect_kgrowth.py --since 2024-01-01 --max-pages 200 --resume`(이미 받은 글은 건너뛰고 이어 받음).
- 매시 봇이 `data/`를 커밋하므로 push가 거절되기 쉽다. 커밋은 **파일을 지정해서** 하고,
  거절되면 `git fetch && git rebase -X theirs origin/main && git push`. 백그라운드 작업이 data 파일을 쓰는 동안
  `--autostash`나 `git reset --hard`를 쓰지 않는다(작업 중인 파일이 되돌려진 적이 있음).
- 화면 확인 폭: 휴대폰 412px, 폴드 펼침 673·884px, 데스크톱 1440px.
  640px 이상은 왼쪽 출자사업·오른쪽 뉴스 2단, 그 미만은 1단. 900px 이하는 글자를 키우고 좌우 여백을 줄임.
  달력 칸(계획·접수·기타·마감·심사·발표)은 모두 같은 `.dots .dot` 칩이며 `fitCal()`이 글자 크기를 맞춘다.

## 현재 상태 (2026-11-28)
- 모든 기관 2024-01-01부터 과거 자료 채움 완료. 단 한국성장금융·신한자산운용은 2026-11-28에 다시 채우는 중이었다
  (성장금융은 상세 1건 실패로 중단돼 수집기를 고친 뒤 재실행). `data/kgrowth.json`의 가장 오래된 글이
  2024년이 아니면 위 `--resume` 명령을 다시 돌린 뒤 `py scripts/extract_dates.py --since 2024-01-01 --limit 300`으로
  일정을 뽑는다(성장금융 첨부는 60초 간격이라 오래 걸리므로 백그라운드로).
- 달력의 접수마감 일정: 약 90건(첨부파일에서 추출).
