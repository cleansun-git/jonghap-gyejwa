# -*- coding: utf-8 -*-
"""시세 조회 (한국투자증권 KIS OpenAPI).

  오래 돌려 검증된 부분만 남겨 둔 조회 코드다
  (재시도가 붙은 http_json, 24시간 토큰 캐시, 현재가·종목명 조회).

안전장치 두 가지 (없애지 말 것):
  - 0원 가드   : KIS 는 모르는 종목코드에도 rt_cd=0 과 값이 전부 0인 응답을 준다.
                 0원을 그대로 반영하면 평가금액이 0이 되므로 실패로 처리한다.
  - 종목명 대조 : 조회한 실제 종목명이 state 의 이름과 다르면 그 종목은 건너뛴다.
                 과거 잘못된 종목코드로 엉뚱한 시세가 들어간 사고가 있었다.

KIS 키가 없어도 앱 전체는 정상 동작해야 한다(현재가를 손으로 넣으면 되므로).
그래서 이 모듈은 키가 없을 때 예외를 던지지 않고 refresh_prices() 가
{"ok": False, ...} 로 조용히 돌아온다.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request

import settings

log = logging.getLogger(__name__)

# 토큰 캐시는 data/ 에 둔다 — 재배포해도 살아남는 유일한 폴더이고 .gitignore 대상이다.
TOKEN_CACHE_PATH = os.path.join(settings.DATA_DIR, ".kis_token_cache.json")

REAL_BASE = "https://openapi.koreainvestment.com:9443"       # 실전투자
PAPER_BASE = "https://openapivts.koreainvestment.com:29443"  # 모의투자

REQUEST_INTERVAL_SEC = 0.6  # 호출 간 대기(KIS 초당 거래건수 제한 보호용)
MAX_RETRY = 3               # 속도 제한/일시적 네트워크 오류 시 재시도 횟수

# 키가 없을 때 화면에 그대로 뿌리는 문구. 오류가 아니라 '아직 안 넣었다'는 안내다.
NO_KEY_MESSAGE = ("KIS 키가 설정되지 않았습니다. "
                  "secrets.json 에 kis_app_key/kis_app_secret 을 넣어주세요.")

# 서버가 UTC 로 돌아도 '오늘'은 한국 장 기준이어야 priceDate 가 어긋나지 않는다.
KST = dt.timezone(dt.timedelta(hours=9))


def load_keys() -> dict | None:
    """KIS 키를 읽는다. 없거나 예시값 그대로면 None (호출자가 조용히 물러난다).

    settings 를 통해 읽으므로 환경변수(PEN_KIS_APP_KEY)도 그대로 먹힌다.
    config.yaml 이 깨져 settings.load() 가 죽더라도 시세 갱신만 못 할 뿐
    앱이 통째로 멈추면 안 되므로 여기서 잡아 None 으로 바꾼다.
    """
    try:
        cfg = settings.load()
    except Exception as e:  # noqa: BLE001
        log.warning("설정을 읽지 못해 시세 갱신을 건너뜁니다 (%s)", e)
        return None

    app_key = cfg.kis_app_key
    app_secret = cfg.kis_app_secret
    if not app_key or not app_secret:
        return None
    # secrets.example.json 을 복사만 해두고 값을 안 바꾼 경우도 '없음'으로 본다.
    if "xxxxxxxx" in app_key.lower() or "xxxxxxxx" in app_secret.lower():
        return None

    paper = cfg.kis_paper
    return {"app_key": app_key, "app_secret": app_secret,
            "base": PAPER_BASE if paper else REAL_BASE}


def http_json(url, headers, body=None, method="GET"):
    """KIS API 호출.

    초당 거래건수 제한(EGW00201)뿐 아니라 DNS 실패·연결 끊김 같은 일시적 네트워크
    오류도 재시도한다. 끝내 실패하면 RuntimeError 로 바꿔 던져, 종목 단위 예외
    처리에서 걸리도록 한다(네트워크가 잠깐 끊겨도 갱신 전체가 죽지 않게).
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    last_err = None
    for attempt in range(MAX_RETRY):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore")
            last_err = RuntimeError(f"HTTP {e.code}: {detail[:300]}")
            if "EGW00201" in detail and attempt < MAX_RETRY - 1:
                time.sleep(1.0 * (attempt + 1))  # 점점 더 오래 대기
                continue
            raise last_err
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
            # DNS 실패(getaddrinfo), 연결 거부, 타임아웃 등. 절전에서 막 깨어난 직후에 흔하다.
            last_err = RuntimeError(f"네트워크 오류: {e}")
            if attempt < MAX_RETRY - 1:
                time.sleep(2.0 * (attempt + 1))
                continue
            raise last_err
    raise last_err


def get_access_token(base, app_key, app_secret):
    """접근토큰을 발급한다.

    KIS는 토큰 발급을 1분당 1회로 제한하고 토큰 자체는 24시간 유효하므로,
    받은 토큰을 파일에 캐싱해 만료 전까지 재사용한다.

    원본(update_prices.py)은 CLI 라 실패를 SystemExit 으로 끝냈지만, 여기서는
    웹 서버 안에서 도는 코드라 프로세스를 죽이면 안 된다. 안내 문구는 그대로 두고
    RuntimeError 로 바꿔 던져 refresh_prices() 가 {"ok": False} 로 감싸게 한다.
    """
    now = time.time()
    if os.path.exists(TOKEN_CACHE_PATH):
        try:
            with open(TOKEN_CACHE_PATH, "r", encoding="utf-8") as f:
                cached = json.load(f)
            # 만료 10분 전부터는 새로 발급받는다.
            if cached.get("base") == base and cached.get("expires_at", 0) - 600 > now:
                return cached["access_token"]
        except (ValueError, OSError):
            pass  # 캐시가 깨졌으면 새로 발급

    url = f"{base}/oauth2/tokenP"
    headers = {"content-type": "application/json; charset=UTF-8"}
    body = {"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret}
    try:
        res = http_json(url, headers, body, method="POST")
    except RuntimeError as e:
        msg = str(e)
        if "EGW00133" in msg:
            raise RuntimeError(
                "접근토큰 발급이 1분당 1회로 제한됩니다. 1분 뒤 다시 시도해주세요. "
                "(한 번 발급되면 24시간 동안 재사용됩니다)"
            ) from e
        if "네트워크 오류" in msg:
            raise RuntimeError(
                "KIS 서버에 접속할 수 없습니다. 인터넷 연결을 확인해주세요."
            ) from e
        raise

    token = res.get("access_token")
    if not token:
        raise RuntimeError(f"토큰 발급에 실패했습니다: {res.get('msg1') or res}")

    expires_in = int(res.get("expires_in", 86400))
    try:
        os.makedirs(settings.DATA_DIR, exist_ok=True)
        with open(TOKEN_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"access_token": token, "expires_at": now + expires_in,
                       "base": base}, f)
    except OSError:
        pass  # 캐시 저장에 실패해도 이번 갱신은 계속 진행
    return token


def get_current_price(base, app_key, app_secret, token, code):
    url = (
        f"{base}/uapi/domestic-stock/v1/quotations/inquire-price"
        f"?fid_cond_mrkt_div_code=J&fid_input_iscd={code}"
    )
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST01010100",
        "custtype": "P",
    }
    res = http_json(url, headers, method="GET")
    if res.get("rt_cd") != "0":
        # msg_cd 를 앞에 붙여 둔다. 토큰이 거절된 경우(EGW00121/EGW00123)를
        # 문구가 아니라 코드로 가려내야 refresh_prices 가 토큰을 다시 받을 수 있다.
        raise RuntimeError(f"{res.get('msg_cd', '')} {res.get('msg1', '조회 실패')}".strip())
    output = res.get("output", {})
    price = output.get("stck_prpr")
    if price is None or price == "":
        raise RuntimeError("응답에 현재가(stck_prpr) 없음")

    price = int(price)
    # KIS는 인식하지 못하는 종목코드에도 rt_cd=0 과 함께 모든 값이 0인
    # 빈 응답을 돌려준다. 이걸 그대로 반영하면 평가금액이 0원이 되어버리므로
    # 0원은 정상 시세로 취급하지 않고 실패로 처리한다.
    if price <= 0:
        raise RuntimeError("현재가 0원 (종목코드 확인 필요 - 상장폐지/코드오류 가능성)")
    return price


def get_stock_name(base, app_key, app_secret, token, code):
    """종목코드에 실제로 등록된 종목명을 조회한다(코드 오입력 검증용)."""
    url = f"{base}/uapi/domestic-stock/v1/quotations/search-stock-info?PRDT_TYPE_CD=300&PDNO={code}"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "CTPF1002R",
        "custtype": "P",
    }
    try:
        res = http_json(url, headers, method="GET")
    except RuntimeError:
        return None
    if res.get("rt_cd") != "0":
        return None
    o = res.get("output", {})
    return (o.get("prdt_abrv_name") or o.get("prdt_name") or "").strip() or None


WD_KO = ("월", "화", "수", "목", "금", "토", "일")


def is_market_open(when: dt.date | None = None) -> tuple[bool, str]:
    """오늘 국내 장이 열리는 날인가. -> (열림?, 사유)

    공휴일 목록을 코드에 박아두면 매년 손봐야 하고 임시공휴일은 놓친다.
    그래서 KIS 휴장일 API(CTCA0903R)에 직접 묻는다.

    **조회에 실패하면 '열린 날'로 본다.** 공휴일에 어제와 같은 값이 한 줄 더 남는 것은
    upsert 로 덮이는 가벼운 손해지만, API 장애로 평일 마감을 통째로 빠뜨리면
    그날 기록이 영영 비고 알림도 오지 않는다. 주말만은 API 없이도 거른다.

    KIS 키 없이 쓰는 경우(이 배포형의 기본): 휴장일을 확인할 방법이 아예 없으므로
    주말만 거르고 평일은 모두 개장일로 둔다. 그래서 공휴일에도 마감 한 줄이 쌓인다.
    현재가를 손으로 넣는 앱이라 그 줄은 전날과 같은 값이고, 다음 날 덮이거나
    성과 탭에서 평평한 구간으로 보일 뿐이다. 공휴일 줄까지 막고 싶으면 아래
    '키 없음' 분기를 False 로 바꾸면 되지만, 그러면 평일 기록도 같이 멈춘다.
    """
    d = when or dt.datetime.now(KST).date()
    if d.weekday() >= 5:
        return False, f"주말({WD_KO[d.weekday()]})"

    keys = load_keys()
    if not keys:
        # 확인한 것이 아니라 확인할 수 없었다는 뜻이다. 로그가 이 둘을 섞지 않게 한다.
        return True, "KIS 키 없음 — 휴장일 확인 불가(주말만 거름)"

    ymd = d.strftime("%Y%m%d")
    try:
        token = get_access_token(keys["base"], keys["app_key"], keys["app_secret"])
        url = (f"{keys['base']}/uapi/domestic-stock/v1/quotations/chk-holiday"
               f"?BASS_DT={ymd}&CTX_AREA_NK=&CTX_AREA_FK=")
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": keys["app_key"],
            "appsecret": keys["app_secret"],
            "tr_id": "CTCA0903R",
            "custtype": "P",
        }
        res = http_json(url, headers, method="GET")
    except Exception as e:  # noqa: BLE001
        return True, f"휴장일 조회 오류(개장일로 간주): {e}"

    if res.get("rt_cd") != "0":
        return True, f"휴장일 조회 실패(개장일로 간주): {res.get('msg1', '')}".strip()
    # 응답은 BASS_DT 부터 며칠치가 한꺼번에 온다. 오늘 줄만 골라 본다.
    for row in (res.get("output") or []):
        if str(row.get("bass_dt")) == ymd:
            if str(row.get("opnd_yn", "")).upper() == "Y":
                return True, "개장일"
            return False, "휴장일(공휴일)"
    return True, "휴장일 목록에 없음(개장일로 간주)"


# KIS 가 토큰을 거절할 때 주는 코드. 유효하지 않은 토큰 / 기간이 만료된 토큰.
TOKEN_ERROR_CODES = ("EGW00121", "EGW00123")


def is_token_error(msg) -> bool:
    """캐시해 둔 토큰을 KIS 가 거절했는가.

    캐시 파일상으로는 아직 24시간이 안 지났어도 KIS 쪽에서 토큰이 무효가 되는 일이
    있다(같은 키를 쓰는 다른 프로그램이 새로 발급받는 경우 등).
    그러면 모든 종목이 같은 사유로 실패해 그날 시세를 통째로 놓친다.
    """
    m = str(msg or "")
    return any(c in m for c in TOKEN_ERROR_CODES)


def drop_token_cache() -> None:
    try:
        os.remove(TOKEN_CACHE_PATH)
    except OSError:
        pass


def normalize(s):
    """종목명 비교용 정규화: 공백/괄호/특수문자 제거 후 소문자화."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def _lookup(base, app_key, app_secret, token, code, cache):
    """종목명·현재가를 조회한다. 한 번의 갱신 안에서 같은 종목코드는 한 번만 호출한다.

    (같은 종목을 두 줄로 나눠 들고 있어도 호출은 한 번이면 된다)
    """
    if code in cache:
        return cache[code]

    real_name = get_stock_name(base, app_key, app_secret, token, code)
    time.sleep(REQUEST_INTERVAL_SEC)
    try:
        price = get_current_price(base, app_key, app_secret, token, code)
        err = None
    except Exception as e:  # noqa: BLE001 - 어떤 실패든 종목 단위로만 건너뛴다
        price, err = None, str(e)
    time.sleep(REQUEST_INTERVAL_SEC)

    cache[code] = (real_name, price, err)
    return cache[code]


def _as_int(value) -> int:
    """숫자로 못 읽는 값은 0. 손으로 고친 state.json 에 문자열이 들어와도 죽지 않게."""
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _apply_price(holding: dict, price: int, today: str) -> None:
    """현재가를 반영한다. 날짜가 바뀐 뒤 첫 갱신에서만 직전값을 prevPrice 로 민다.

    같은 날 두 번 갱신해도 prevPrice 가 '직전 거래일 종가'로 남아 있어야
    전일대비가 0 으로 무너지지 않는다 (SPEC §2).
    """
    if str(holding.get("priceDate") or "") != today:
        prev = _as_int(holding.get("price"))
        if prev > 0:                       # 0 을 직전 종가로 남기면 등락률이 튄다
            holding["prevPrice"] = prev
    holding["price"] = int(price)
    holding["priceDate"] = today


def refresh_prices(state: dict) -> dict:
    """보유 종목의 현재가를 KIS 시세로 갱신한다.

    반환: {"ok", "message", "updated", "failed":[{"code","name","reason"}]}

    state 를 여기서 저장하지 않는 이유: 저장은 store 를 쥔 service.py 한 곳에서만
    일어나야 백업·원자적 교체 규칙이 한 군데로 모인다. 여기서는 넘겨받은 dict 만 고친다.
    """
    keys = load_keys()
    if keys is None:
        return {"ok": False, "message": NO_KEY_MESSAGE, "updated": 0, "failed": []}

    holdings = [h for h in (state.get("holdings") or []) if isinstance(h, dict)]
    if not holdings:
        return {"ok": True, "message": "갱신할 종목이 없습니다.", "updated": 0, "failed": []}

    base, app_key, app_secret = keys["base"], keys["app_key"], keys["app_secret"]
    try:
        token = get_access_token(base, app_key, app_secret)
    except Exception as e:  # noqa: BLE001
        # 토큰이 없으면 한 종목도 조회하지 못한다. 실패 목록은 비워두고 사유만 알린다.
        log.warning("KIS 토큰 발급 실패: %s", e)
        return {"ok": False, "message": str(e), "updated": 0, "failed": []}

    today = dt.datetime.now(KST).date().isoformat()
    cache: dict = {}
    updated = 0
    failed: list[dict] = []
    reissued = False            # 토큰 재발급은 한 번만 — KIS 가 키당 1분 1회만 허용한다

    for h in holdings:
        code = str(h.get("code") or "").strip()
        name = str(h.get("name") or "").strip()
        if not code:
            failed.append({"code": "", "name": name, "reason": "종목코드가 비어 있습니다."})
            continue

        try:
            real_name, price, err = _lookup(base, app_key, app_secret, token, code, cache)
            if price is None and is_token_error(err) and not reissued:
                # 캐시된 토큰이 거절됐다. 캐시를 버리고 한 번만 새로 받아 이 종목부터 다시 조회한다.
                # 거절된 토큰으로는 종목명 조회도 조용히 None 이 되므로 그 결과도 버린다.
                reissued = True
                log.warning("KIS 가 캐시된 토큰을 거절해 새로 발급받습니다 (%s)", err)
                drop_token_cache()
                token = get_access_token(base, app_key, app_secret)
                cache.pop(code, None)
                real_name, price, err = _lookup(base, app_key, app_secret, token, code, cache)
        except Exception as e:  # noqa: BLE001 - 한 종목이 실패해도 나머지는 계속 조회한다
            log.warning("%s(%s) 조회 실패: %s", name, code, e)
            failed.append({"code": code, "name": name, "reason": str(e)})
            continue

        # 안전장치 2 — 종목명 대조. 코드가 다른 종목을 가리키면 엉뚱한 시세가 들어가
        # 평가금액이 통째로 어긋난다. 이름이 비어 있으면 대조할 게 없으므로 통과시킨다.
        if real_name and name and normalize(name) != normalize(real_name):
            log.warning("종목명 불일치 %s: 기록='%s' 실제='%s'", code, name, real_name)
            failed.append({"code": code, "name": name,
                           "reason": f"종목명이 다릅니다 (실제 '{real_name}'). 종목코드를 확인해주세요."})
            continue

        # 안전장치 1 — 0원 가드는 get_current_price 안에서 이미 실패로 바뀌어 온다.
        if price is None:
            failed.append({"code": code, "name": name, "reason": err or "조회에 실패했습니다."})
            continue

        _apply_price(h, price, today)
        updated += 1

    if updated:
        # 화면의 '마지막 갱신'과 priceStale 판정이 보는 값. 한 종목이라도 새로 받았을 때만 찍는다.
        state["priceUpdatedAt"] = dt.datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S")

    message = f"{len(holdings)}종목 중 {updated}종목 갱신했습니다."
    if failed:
        message += f" {len(failed)}종목은 이전 값을 그대로 두었습니다."
    return {"ok": updated > 0, "message": message, "updated": updated, "failed": failed}
