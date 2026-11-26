"""한국산업은행 공지사항 '글 상세' 주소를 만든다.

산업은행 사이트는 목록에서 제목을 누르면 아래 형태의 주소로 이동한다(GET, 로그인·쿠키 불필요).
  /BOUBUF02N00.act?...&_PARM_DATA={글 번호 등 JSON}&_PARM_DATA_SIGN={서명}
서명은 사이트 화면 스크립트(_gf.getSimpleSign)가 계산하는 간단한 값이며, 같은 계산을 여기서 재현한다.
  1단계: 글자마다  sign = sign*31 + 문자코드  (32비트 정수)
  2단계: 1단계 결과 숫자를 글자열로 바꿔 같은 계산을 한 번 더 한다.
산업은행 화면이 바뀌면 서명 계산이 달라질 수 있으니, 링크가 안 열리면 이 파일부터 확인한다.
"""
import json
from urllib.parse import quote

BASE = "https://www.kdb.co.kr/BOUBUF02N00.act"


def _js_hash(s):
    h = 0
    for ch in s:
        h = ((h << 5) - h) + ord(ch)
        h = (h + 2**31) % 2**32 - 2**31  # JS의 `|= 0`(32비트 정수로 자르기)
    return h


def sign(data):
    return _js_hash(str(_js_hash(data)))


def detail_url(sno):
    params = {"ITR_NAC_ID_MNG_SNO": str(sno), "ITR_BLB_ID": "STD119", "NAC_SNO": "", "SEARCH_CONDITION": "ZZ",
              "SEARCH_KEYWORD": "", "SEARCH_CATEGORY": "ZZ", "ORDER_TYPE": "new", "FIRST_MENU_ID": "CHBIPR23N00",
              "TAB": "", "viewPage": "10", "searchCondition": "ZZ", "searchKeyword": "", "searchCategory": "ZZ",
              "inqCntSotYn": "sortNew", "pageNo": 1, "GmBrnId": "", "tabYn": "", "popupYn": "", "replyCntYn": ""}
    data = json.dumps(params, ensure_ascii=False, separators=(",", ":"))
    return (f"{BASE}?GmBrnId=&tabYn=&popupYn=&replyCntYn=&ECY_PWD=&_mnuId=IHIHIR0087"
            f"&_PARAM_NAME=NEXT_DATA&_PARM_DATA={quote(data, safe='')}&_PARM_DATA_SIGN={sign(data)}")
