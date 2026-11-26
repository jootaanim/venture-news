"""인증서 검증용 묶음 파일을 만든다.

일부 기관 서버(신한벤처투자, 수출입은행)는 중간 인증서를 빼고 내려준다. 브라우저는 알아서 보완하지만
수집기는 검증에 실패한다. 인증서 검증을 끄는 대신, 발급기관이 공식 주소에 올려둔 중간 인증서를
certs/*.pem 에 두고 기본 신뢰 목록(certifi)에 더해 검증을 그대로 켠 채 접속한다.
"""
from pathlib import Path

import certifi

ROOT = Path(__file__).resolve().parent.parent


def ca_bundle():
    out = ROOT / ".cache" / "ca_bundle.pem"
    out.parent.mkdir(parents=True, exist_ok=True)
    extra = "\n".join(p.read_text() for p in sorted((ROOT / "certs").glob("*.pem")))
    out.write_text(Path(certifi.where()).read_text() + "\n" + extra)
    return str(out)
