# -*- coding: utf-8 -*-
"""종합계좌 웹앱 — FastAPI 백엔드 + PWA 서빙.

  · 평일 16:05(KST) 자동 실행 (APScheduler): 시세 갱신 → 오늘 마감 저장 → 푸시
  · 웹앱에서 현황 조회 / 체결 기록 / 종목·현금·배당 관리
  · 웹 푸시 알림 (선택)

이 파일은 라우팅과 입력 모양(Pydantic)만 맡는다. 계산은 전부 web/service.py 에 있다.
전략 엔진이 없으므로 주문을 계산하지 않는다 — 실제로 한 매매를 기록하고 보여줄 뿐이다.

실행:  uvicorn web.app:app --host 0.0.0.0 --port 8010
"""
from __future__ import annotations

import contextlib
import datetime as dt
import logging
import os
import secrets as pysecrets
import sys
import threading
import time

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import accounts           # noqa: E402
import service            # noqa: E402
import settings           # noqa: E402
import push as pushmod    # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s")
log = logging.getLogger("app")

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
KST = dt.timezone(dt.timedelta(hours=9))
COOKIE = "pen_session"
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}

try:
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as _f:
        VERSION = _f.read().strip()
except OSError:
    VERSION = "0.0.0"

# openapi_url=None 인 이유: docs/redoc 만 끄면 /openapi.json 이 그대로 열려 있어
# 포트에 닿는 누구나 API 전체 목록을 받아볼 수 있다. 이 앱에는 필요가 없다.
app = FastAPI(title="종합계좌", version=VERSION,
              docs_url=None, redoc_url=None, openapi_url=None)


# ---------------------------------------------------------------------------
# 인증 — 단일 사용자. 비밀번호는 환경변수 PEN_PASSWORD 로 준다.
# ---------------------------------------------------------------------------
def _password() -> str:
    """PEN_PASSWORD → secrets.json 순서로 찾는다 (settings 가 그 순서를 안다)."""
    try:
        return settings.load().web_password
    except Exception:  # noqa: BLE001
        # config.yaml 이 깨져 설정을 못 읽어도 로그인은 되어야 한다.
        return os.environ.get("PEN_PASSWORD", "").strip()


def _is_local(request: Request) -> bool:
    return bool(request.client) and request.client.host in LOCAL_HOSTS


NO_PW_MSG = ("비밀번호가 설정되지 않았습니다. 이 PC 밖에서 쓰시려면 반드시 "
             "비밀번호를 설정해야 합니다. (secrets.json 의 web_password 또는 "
             "환경변수 PEN_PASSWORD. 자세한 것은 README 를 보세요)")

_SESSIONS: set[str] = set()


def require_auth(request: Request) -> None:
    pw = _password()
    if not pw:
        # 비밀번호 미설정 = 내 PC 에서 혼자 써보는 개발 모드.
        # 외부에서 들어온 요청까지 열어주면 남이 내 계좌 상태를 보고
        # 고칠 수 있으므로, 이 경우에는 막는다.
        if _is_local(request):
            return
        raise HTTPException(status_code=401, detail=NO_PW_MSG)
    tok = request.cookies.get(COOKIE, "")
    if tok not in _SESSIONS:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")


class LoginIn(BaseModel):
    password: str


# ---------------------------------------------------------------------------
# 로그인 시도 제한 — fly.io 로 인터넷에 열리면 누구나 비밀번호를 두드려 볼 수 있다.
#   · 같은 곳에서 10분에 5번 틀리면 그곳은 10분 동안 막는다.
#   · 전체로 10분에 15번 틀리면 모두 막는다 — 접속 주소를 바꿔가며 두드리는 경우까지 묶는다.
# 맞는 비밀번호도 막힌 동안은 받지 않는다. 막힌 동안 맞는 것만 통과시키면
# '429 냐 200 이냐' 로 정답을 알아낼 수 있어 제한이 의미가 없어진다.
# 대가로 누가 일부러 틀리면 주인도 10분 못 들어오지만, 개인용 앱이라 그 편이 낫다.
# ---------------------------------------------------------------------------
_FAIL_WINDOW = 600
_FAIL_PER_CLIENT = 5
_FAIL_GLOBAL = 15
_FAILS: dict[str, list[float]] = {}
_FAILS_LOCK = threading.Lock()


def _client_key(request: Request) -> str:
    """fly.io 는 프록시 뒤라 request.client 가 전부 프록시 주소로 보인다.
    Fly-Client-IP 는 fly 프록시가 채워 주는 실제 접속 주소라 그것을 먼저 쓴다."""
    return (request.headers.get("fly-client-ip")
            or (request.client.host if request.client else "?"))


def _login_blocked(key: str, now: float) -> bool:
    with _FAILS_LOCK:
        for k in list(_FAILS):
            _FAILS[k] = [t for t in _FAILS[k] if now - t < _FAIL_WINDOW]
            if not _FAILS[k]:
                del _FAILS[k]
        total = sum(len(v) for v in _FAILS.values())
        return len(_FAILS.get(key, [])) >= _FAIL_PER_CLIENT or total >= _FAIL_GLOBAL


def _login_failed(key: str, now: float) -> None:
    with _FAILS_LOCK:
        _FAILS.setdefault(key, []).append(now)


@app.post("/api/login")
def login(body: LoginIn, request: Request, response: Response):
    pw = _password()
    if not pw:
        if _is_local(request):
            return {"ok": True, "message": "비밀번호가 설정되지 않아 열려 있습니다."}
        raise HTTPException(status_code=401, detail=NO_PW_MSG)
    key, now = _client_key(request), time.time()
    if _login_blocked(key, now):
        raise HTTPException(status_code=429,
                            detail="로그인 시도가 너무 많습니다. 10분 뒤에 다시 시도해주세요.")
    # compare_digest 는 str 을 받으면 ASCII 만 허용한다 — 한글 비밀번호를 그대로 넘기면
    # TypeError 가 나면서 맞는 비밀번호로도 500 이 떨어져 영영 못 들어온다.
    # UTF-8 바이트로 바꿔서 비교하면 한글·이모지도 안전하고, 상수시간 비교도 그대로 유지된다.
    if not pysecrets.compare_digest(body.password.encode("utf-8"), pw.encode("utf-8")):
        _login_failed(key, now)
        time.sleep(0.4)     # 틀릴 때마다 조금 늦춰 연속 대입을 더 비싸게 만든다
        raise HTTPException(status_code=401, detail="비밀번호가 맞지 않습니다.")
    tok = pysecrets.token_urlsafe(32)
    _SESSIONS.add(tok)
    # 집 WiFi 는 https 가 아니라 secure 쿠키를 쓰면 로그인이 아예 안 된다.
    # 그래서 PEN_HTTPS=0 으로 끌 수 있게 열어 둔다 (기본값은 켜짐).
    response.set_cookie(COOKIE, tok, httponly=True, samesite="lax",
                        secure=os.environ.get("PEN_HTTPS", "1") == "1",
                        max_age=60 * 60 * 24 * 90)
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    _SESSIONS.discard(request.cookies.get(COOKIE, ""))
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/auth")
def auth_state(request: Request):
    pw = _password()
    open_mode = (not pw) and _is_local(request)
    return {"required": not open_mode,
            "authed": open_mode or request.cookies.get(COOKIE, "") in _SESSIONS,
            "version": VERSION,
            "accounts": accounts.ACCOUNTS}


# ---------------------------------------------------------------------------
# 계좌 — 탭 하나 = 계좌 하나 (?account=isa)
# ---------------------------------------------------------------------------
def require_account(account: str = accounts.DEFAULT) -> str:
    """?account= 값을 등록부의 key 로 바꾼다. 모르는 값이면 400.

    이 key 는 data/<key>/ 경로에 그대로 들어간다. 등록부와 대조하지 않으면
    바깥에서 보낸 문자열이 그대로 파일 경로가 되므로, 반드시 여기를 거친다.
    account 를 안 보내면 퇴직연금(기본 계좌)이다 — 예전 클라이언트도 그대로 돈다.
    """
    key = accounts.normalize(account)
    if key is None:
        raise HTTPException(status_code=400, detail="알 수 없는 계좌입니다.")
    return key


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------
@app.get("/api/snapshot")
def api_snapshot(acct: str = Depends(require_account), _: None = Depends(require_auth)):
    return service.snapshot(acct)


@app.get("/api/history")
def api_history(days: int = 180, acct: str = Depends(require_account),
                _: None = Depends(require_auth)):
    return service.history(acct, days)


# ---------------------------------------------------------------------------
# 보유 종목 / 시세 / 현금 / 배당 (퇴직연금 탭)
# ---------------------------------------------------------------------------
class HoldingIn(BaseModel):
    """퇴직연금 탭의 종목 시트에서 오는 본문. id 가 없으면 신규 추가, 있으면 그 종목 수정이다."""

    id: str | None = None
    code: str = ""
    name: str = ""
    asset: str = ""
    pay: str = ""
    qty: int = 0
    buyPrice: float = 0            # noqa: N815 - 프런트와 맞춘 이름이라 그대로 둔다
    price: float = 0
    memo: str = ""
    action: str = "edit"           # edit | buy | sell
    deltaQty: int = 0              # noqa: N815
    deltaPrice: float = 0          # noqa: N815
    confirm_price: bool = False    # 현재가가 오타가 아님을 사용자가 승인
    confirm_dup: bool = False      # 방금 같은 매수·매도를 한 번 더 넣는 것을 사용자가 승인


@app.post("/api/holding")
def api_holding(body: HoldingIn, acct: str = Depends(require_account),
                _: None = Depends(require_auth)):
    try:
        return service.save_holding(acct, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class HoldingDeleteIn(BaseModel):
    id: str


@app.post("/api/holding/delete")
def api_holding_delete(body: HoldingDeleteIn, acct: str = Depends(require_account),
                       _: None = Depends(require_auth)):
    try:
        return service.delete_holding(acct, body.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class PricesIn(BaseModel):
    prices: dict[str, float] = {}   # {종목id: 현재가}


@app.post("/api/prices")
def api_prices(body: PricesIn, acct: str = Depends(require_account),
               _: None = Depends(require_auth)):
    try:
        return service.set_prices(acct, body.prices)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/refresh-prices")
def api_refresh_prices(acct: str = Depends(require_account),
                       _: None = Depends(require_auth)):
    """KIS 시세 자동 갱신. 키가 없거나 조회가 실패해도 200 으로 조용히 돌아온다."""
    return service.refresh_prices(acct)


class CashIn(BaseModel):
    amount: float = 0


@app.post("/api/cash")
def api_cash(body: CashIn, acct: str = Depends(require_account),
             _: None = Depends(require_auth)):
    try:
        return service.set_cash(acct, body.amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class DividendIn(BaseModel):
    code: str = ""
    name: str = ""
    amount: float = 0
    date: str | None = None


@app.post("/api/dividend")
def api_dividend(body: DividendIn, acct: str = Depends(require_account),
                 _: None = Depends(require_auth)):
    try:
        return service.add_dividend(acct, body.code, body.name, body.amount, body.date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class StrategyIn(BaseModel):
    text: str = ""


@app.post("/api/strategy")
def api_strategy(body: StrategyIn, acct: str = Depends(require_account),
                 _: None = Depends(require_auth)):
    return service.set_strategy(acct, body.text)


@app.post("/api/close-today")
def api_close_today(acct: str = Depends(require_account),
                    _: None = Depends(require_auth)):
    try:
        return service.close_today(acct)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# 설정 탭
# ---------------------------------------------------------------------------
class StartIn(BaseModel):
    start_date: str | None = None


@app.post("/api/start")
def api_start(body: StartIn, acct: str = Depends(require_account),
              _: None = Depends(require_auth)):
    try:
        return service.set_start_date(acct, body.start_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="날짜 형식은 YYYY-MM-DD 입니다.")


@app.post("/api/run-now")
def api_run_now(_: None = Depends(require_auth)):
    """지금 즉시 일일 실행 (시세 갱신 + 오늘 마감 저장 + 알림)."""
    n = run_daily_job(manual=True)
    return {"ok": True, "message": n}


# ---------------------------------------------------------------------------
# 웹 푸시
# ---------------------------------------------------------------------------
@app.get("/api/push/key")
def push_key(_: None = Depends(require_auth)):
    return {"publicKey": pushmod.public_key()}


@app.post("/api/push/subscribe")
async def push_subscribe(request: Request, _: None = Depends(require_auth)):
    pushmod.add_subscription(await request.json())
    return {"ok": True}


@app.post("/api/push/test")
def push_test(_: None = Depends(require_auth)):
    n = pushmod.send_all("퇴직연금", "알림 테스트입니다. 정상 동작합니다.")
    return {"ok": True, "sent": n}


# ---------------------------------------------------------------------------
# 평일 16:05 KST 실행 (시각은 config.yaml 의 notify.daily_hour/daily_minute)
# ---------------------------------------------------------------------------
def run_daily_job(manual: bool = False) -> str:
    """등록된 계좌를 한 바퀴 돌며 시세 갱신 → 오늘 마감 저장 → 푸시(한 번).

    계좌마다 알림을 보내면 하루에 알림이 계좌 수만큼 울린다. 마감은 계좌별로 따로
    저장하고, 알림은 합쳐서 한 통만 보낸다.
    한 계좌가 실패해도 나머지는 계속한다 — ISA 가 막혔다고 퇴직연금 기록까지
    빠뜨릴 이유가 없다.
    """
    import market                                        # noqa: PLC0415

    done, notes = [], []
    for acct in accounts.KEYS:
        try:
            r = _run_one_account(acct, manual)
        except Exception as e:  # noqa: BLE001
            log.exception("%s 일일 실행 실패", acct)
            notes.append(f"{accounts.label(acct)} 실패({type(e).__name__})")
            continue
        if r is None:                       # 휴장일 등 — 아무것도 하지 않았다
            continue
        done.append(r)
        if r.get("note"):
            notes.append(r["note"])

    body = _daily_body(done, notes)
    # 보낼 말이 없으면(=휴장일이라 모든 계좌를 건너뛰었으면) 알림도 보내지 않는다.
    # 여기서 body 가 아니라 '한 계좌라도 돌았는가' 로 판단하면 휴장일에 빈 알림이 간다.
    if body and _push_on():
        pushmod.send_all(f"오늘 마감 · {str(service.today_kst())[5:]}", body, url="/")
    return body


def _short_krw(v: int) -> str:
    """알림용 짧은 금액. 계좌가 여섯 개라 원 단위로 다 적으면 알림이 잘린다.
    (화면에는 원 단위 그대로 나오므로 여기서만 줄인다. 프런트 kshort() 와 같은 규칙)"""
    n, sign = abs(int(v)), "−" if v < 0 else ""
    if n < 10000:
        return f"{sign}{n:,}원"
    eok, man = n // 100000000, (n % 100000000) // 10000
    if eok:
        return f"{sign}{eok}억" + (f" {man:,}만" if man else "")
    return f"{sign}{man:,}만"


def _daily_body(done: list, notes: list) -> str:
    """알림 본문. 합계를 원 단위로 먼저 보여주고, 계좌별은 짧게 덧붙인다.

    자산이 0 인 계좌(아직 종목을 안 넣은 곳)는 목록에서 뺀다 — 줄만 길어진다.
    """
    if not done and not notes:
        return ""
    parts = []
    if done:
        total = sum(d["total"] for d in done)
        pl = sum(d["evalPl"] for d in done)
        parts.append(f"합계 {total:,}원 ({pl:+,})")
        each = " / ".join(f"{d['label']} {_short_krw(d['total'])}"
                          for d in done if d["total"])
        if each:
            parts.append(each)
    if notes:
        parts.append(" / ".join(notes))
    return " · ".join(parts)


def _push_on() -> bool:
    try:
        return settings.load().push_enabled
    except Exception:  # noqa: BLE001
        return True


def _run_one_account(account: str, manual: bool = False) -> dict | None:
    """계좌 하나의 시세 갱신 + 마감 저장.

    반환: {"label","total","evalPl","note"} — 아무것도 하지 않았으면 None.
    """
    import market                                        # noqa: PLC0415

    snap = service.snapshot(account)
    name = accounts.label(account)
    if not snap["started"] and not manual:
        log.info("%s: 시작일 전이라 건너뜁니다 (start_date=%s)", account, snap["start_date"])
        return None

    # 공휴일엔 시세가 어제 그대로라, 돌려봐야 같은 값을 한 줄 더 남기고 알림만 울린다.
    # 설정 탭의 「지금 실행」(manual)은 사람이 일부러 누른 것이므로 이 검사를 건너뛴다.
    if not manual:
        open_, why = market.is_market_open()
        if not open_:
            log.info("휴장일이라 건너뜁니다 (%s)", why)
            return None                    # 알림 문구에도 넣지 않는다 — 조용히 넘어간다
        log.info("개장일 확인: %s", why)

    if accounts.auto_price(account):
        r = service.refresh_prices(account)
        log.info("%s 시세 갱신: %s", account, r.get("message"))
    else:
        # autoPrice=False 계좌 — 시세는 사람이 넣는다. 마감 기록은 그 값으로 그대로 쌓는다.
        r = {"ok": True, "updated": 0, "message": "자동갱신 대상 아님"}

    # KIS 키가 있는데 한 종목도 못 받았으면(토큰 1분 제한·네트워크 등) 오늘 마감을 저장하지 않는다.
    # 저장하면 어제 시세로 계산한 총자산이 '오늘' 기록으로 남아, 다음 날 전일대비까지 틀어진다.
    # 키가 아예 없는 경우는 다르다 — 손으로 넣은 현재가가 원래 쓰는 값이므로 그대로 마감한다.
    if not r.get("ok") and r.get("message") != market.NO_KEY_MESSAGE and r.get("updated", 0) == 0:
        msg = f"{name}: 시세를 받지 못해 마감을 저장하지 않았습니다. ({r.get('message')})"
        log.warning(msg)
        if _push_on():
            pushmod.send_all(f"마감 저장 실패 · {snap['today'][5:]}",
                             msg + f" {name} 계좌에서 시세 자동갱신 후 관리 > 오늘 마감 저장을 눌러주세요.",
                             url="/")
        return {"label": name, "total": 0, "evalPl": 0, "note": f"{name} 시세 실패"}
    # 마감 저장이 실패해도(보유 0종목이라 총금액 0원인 경우 등) 알림까지 죽이지는 않는다.
    # 예전에는 여기서 ValueError 가 그대로 올라가 '지금 실행' 이 500 을 내고,
    # 스케줄러도 푸시를 못 보낸 채 조용히 끝났다.
    try:
        c = service.close_today(account)
        log.info("%s 마감 저장: %s", account, c.get("message"))
    except ValueError as e:
        log.warning("%s 마감 저장 건너뜀: %s", account, e)

    # 갱신된 값으로 다시 읽어야 알림에 오늘 종가가 실린다.
    t = service.snapshot(account)["totals"]
    return {"label": name, "total": t["total"], "evalPl": t["evalPl"], "note": ""}


def _schedule():
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    hour, minute = 16, 5
    try:
        cfg = settings.load()
        hour, minute = int(cfg.daily_hour), int(cfg.daily_minute)
    except Exception:  # noqa: BLE001
        pass
    sch = BackgroundScheduler(timezone=KST)
    # 주말·공휴일엔 시세가 그대로라 같은 값을 또 저장하게 된다. 평일만 돈다.
    # (공휴일까지 거르려면 달력이 필요한데, 하루 중복 기록은 upsert 로 덮이므로 둔다)
    sch.add_job(run_daily_job, CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute),
                id="daily", misfire_grace_time=3600, coalesce=True)
    sch.start()
    log.info("스케줄러 시작 — 평일 %02d:%02d KST 마감 저장", hour, minute)
    return sch


@contextlib.asynccontextmanager
async def _lifespan(app_: FastAPI):
    """스케줄러 기동/정리.

    on_event("startup") 은 폐기 예정이라 언젠가 조용히 안 불리고, 그러면 매일
    16:05 마감 저장이 아무 소리 없이 멈춘다. lifespan 으로 옮겨 그 위험을 없앤다.
    스케줄러가 못 떠도 앱 자체는 떠야 한다 — 화면으로 손수 기록하는 길은 남는다.
    """
    app_.state.sched = None
    if os.environ.get("PEN_NO_SCHEDULER") != "1":
        try:
            app_.state.sched = _schedule()
        except Exception as e:                           # noqa: BLE001
            log.error("스케줄러를 띄우지 못했습니다 (앱은 계속 동작합니다): %s", e)
    yield
    sch = getattr(app_.state, "sched", None)
    if sch is not None:
        try:
            sch.shutdown(wait=False)
        except Exception:                                # noqa: BLE001
            pass


app.router.lifespan_context = _lifespan


# ---------------------------------------------------------------------------
# PWA 서빙
# ---------------------------------------------------------------------------
@app.get("/favicon.ico")
def favicon():
    """브라우저 탭 아이콘. 링크를 안 보고 이 주소로 바로 찾는 브라우저가 있어 따로 연다."""
    return FileResponse(os.path.join(STATIC, "favicon.ico"), media_type="image/x-icon")


@app.get("/sw.js")
def service_worker():
    # 서비스워커는 캐시되면 갱신이 안 먹어 화면이 옛날 버전에 묶인다.
    return FileResponse(os.path.join(STATIC, "sw.js"), media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"),
                        headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": VERSION,
            "time": dt.datetime.now(KST).isoformat(timespec="seconds")}


@app.middleware("http")
async def _revalidate_assets(request: Request, call_next):
    """app.js·style.css 는 매번 서버에 '바뀌었나' 를 물어보게 한다 (no-cache).

    StaticFiles 는 Cache-Control 을 안 붙이므로 브라우저가 신선도를 멋대로 추정해
    한동안 옛 파일을 쓴다. 그러면 앱을 고친 뒤 새 app.js + 옛 style.css 짝이 되어
    화면이 깨진다 — 실제로 표를 고친 직후 그렇게 보였다.
    집 WiFi(http)에서는 서비스워커가 아예 안 뜨니 sw.js 의 네트워크 우선 정책도
    못 막는다. no-cache 는 캐시를 버리는 게 아니라 ETag 로 확인만 하는 것이라,
    안 바뀌었으면 304 로 몇 바이트만 오간다. 이미지는 바뀔 일이 없어 그대로 둔다.
    """
    resp = await call_next(request)
    if request.url.path.startswith("/static/") and \
            request.url.path.endswith((".js", ".css", ".json", ".html")):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


app.mount("/static", StaticFiles(directory=STATIC), name="static")
