# -*- coding: utf-8 -*-
"""화면에 뿌릴 값을 만들고, 종목 시트에서 온 변경을 반영하는 서비스 계층.

계산은 전부 여기에 모아 둔다. web/app.py 는 라우팅과 입력 모양만 맡는다.

  · snapshot(account)       계좌 탭 한 벌 — 그룹 3개 + 합계 + 전일대비 + 배당
  · history(account, days)  성과 탭 원천 — 일별 기록 · 체결 이력 · 배당 내역
  · save_holding(account,)  종목 시트의 매수 / 매도 / 수정 (가중평균 재계산은 여기서)
  · close_today(account)    오늘 마감을 history.csv 에 남긴다

**계좌(account)는 어느 함수에서도 생략할 수 없다** (2026-09-16 ISA 추가).
기본값을 두면 계좌를 빠뜨린 호출이 조용히 퇴직연금 파일을 건드린다.

금액은 전부 정수 원 단위로 반올림한다 (증권사 화면에도 원 아래는 없다).
비율은 소수로 돌려준다 (-0.0389 = -3.89%). 프런트의 pct() 가 ×100 한다.
나눗셈 분모가 0이면 0.0 — 종목을 막 추가해 매수금액이 0인 상태에서도 화면이 떠야 한다.
"""
from __future__ import annotations

import datetime as dt
import functools
import logging
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import accounts          # noqa: E402
import store             # noqa: E402

log = logging.getLogger("service")

KST = dt.timezone(dt.timedelta(hours=9))

# 그룹은 항상 이 셋을 이 순서로 보낸다. 종목이 0개인 그룹도 빈 items 로 보내야
# 프런트가 "아직 종목이 없습니다"를 그릴 자리를 잃지 않는다 (SPEC §5).
PAY_GROUPS = (("월중", "월중 배당"), ("월말", "월말 배당"), ("기타", "기타"))

# 입력한 현재가가 기존 값과 이만큼 벌어지면 오타로 보고 한 번 되묻는다.
# 12,280 을 1,228 로 적는 자릿수 실수가 실제로 잦다.
PRICE_SANITY_GAP = 0.30

# 시세를 이 날수보다 오래 안 받았으면 화면에 '오래된 시세' 경고를 띄운다.
# 주말(2일) 은 정상이므로 3일로 잡는다.
PRICE_STALE_DAYS = 3

# 종목코드는 6자리 영숫자다 (예: 441640, 0219E0). 형식만 본다 — 실재 여부는
# 시세를 받아올 때 종목명 대조로 걸러진다.
CODE_RE = re.compile(r"^[0-9A-Za-z]{6}$")

# 시세 자동갱신을 쓰지 않는 계좌는 KIS 6자리 규칙을 적용할 수 없다(BTC 처럼 길이가
# 제각각인 티커). 파일명·표시에 문제만 없게 최소한으로 검사한다.
FREE_CODE_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,19}$")


def _code_rule(account: str) -> tuple:
    """(정규식, 틀렸을 때 문구). 계좌 성격에 따라 종목코드 규칙이 다르다."""
    if accounts.auto_price(account):
        return CODE_RE, "종목코드는 6자리 영문·숫자입니다. (예: 441640, 0219E0)"
    return FREE_CODE_RE, "종목코드는 영문·숫자 1~20자입니다. (예: BTC, ETH)"

try:
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as _f:
        VERSION = _f.read().strip()
except OSError:
    VERSION = "0.0.0"


# ---------------------------------------------------------------------------
# 작은 도구들
# ---------------------------------------------------------------------------
def today_kst() -> dt.date:
    """서버가 UTC 로 돌아도 '오늘'은 한국 장 기준이어야 한다."""
    return dt.datetime.now(KST).date()


def _now_iso() -> str:
    """state.json 에 적는 시각. 시드와 같은 모양(초 단위, 시간대 표기 없음)으로 맞춘다."""
    return dt.datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S")


def _int(value, default: int = 0) -> int:
    """금액·수량은 정수 원/주 단위. 손으로 고친 state.json 에 문자열이 와도 죽지 않게."""
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _ratio(part: float, whole: float) -> float:
    """분모가 0이면 0.0. 신규 종목(매수금액 0)에서 화면이 죽지 않게 한다."""
    return (part / whole) if whole else 0.0


def _group_key(pay: str) -> str:
    """월중·월말이 아닌 것(빈 문자열 포함)은 전부 기타 그룹이다."""
    return pay if pay in ("월중", "월말") else "기타"


def _norm_pay(pay: str) -> str:
    """화면의 '기타' 세그먼트는 state.json 에 빈 문자열로 저장한다 (SPEC §2)."""
    p = str(pay or "").strip()
    if p in ("월중", "월말"):
        return p
    if p in ("", "기타"):
        return ""
    raise ValueError("배당시기는 월중 · 월말 · 기타 중에서 골라주세요.")


def _month_label(d: dt.date) -> str:
    return d.strftime("%Y-%m")


def _prev_month_label(d: dt.date) -> str:
    """지난 달. 1일에서 하루 빼면 지난 달 말일이라 연도 넘김도 저절로 맞는다."""
    return _month_label(d.replace(day=1) - dt.timedelta(days=1))


def _apply_price(holding: dict, price: float, today: str) -> None:
    """현재가를 갈아끼운다. 날짜가 바뀐 뒤 첫 갱신에서만 직전값을 prevPrice 로 민다.

    같은 날 두 번 넣어도 prevPrice 가 '직전 거래일 종가'로 남아 있어야
    전일대비가 0 으로 무너지지 않는다 (SPEC §2).
    """
    px = _int(price)
    if str(holding.get("priceDate") or "") != today:
        prev = _int(holding.get("price"))
        if prev > 0:                    # 0 을 직전 종가로 남기면 등락률이 튄다
            holding["prevPrice"] = prev
    holding["price"] = px
    holding["priceDate"] = today
    if _int(holding.get("prevPrice")) <= 0:
        holding["prevPrice"] = px       # 첫 입력이면 비교 대상이 없으니 같은 값


def _price_stale(price_updated_at, now: dt.datetime) -> bool:
    """마지막 시세 갱신이 3일보다 오래됐는가. 못 읽는 값은 오래된 것으로 본다."""
    if not price_updated_at:
        return True
    try:
        ts = dt.datetime.fromisoformat(str(price_updated_at))
    except ValueError:
        return True
    if ts.tzinfo is not None:           # 시간대가 붙어 와도 비교할 수 있게 벗긴다
        ts = ts.astimezone(KST).replace(tzinfo=None)
    return (now - ts) > dt.timedelta(days=PRICE_STALE_DAYS)


# ---------------------------------------------------------------------------
# 퇴직연금 탭 — SNAPSHOT
# ---------------------------------------------------------------------------
def _item(h: dict) -> dict:
    """보유 종목 한 건을 화면용으로 편다 (SPEC §5 ITEM).

    weight 는 총금액이 나온 뒤에야 계산할 수 있어 여기서는 자리만 잡아 둔다.
    """
    qty = _int(h.get("qty"))
    buy_price = _int(h.get("buyPrice"))
    price = _int(h.get("price"))
    prev_price = _int(h.get("prevPrice")) or price
    buy_amount = _int(qty * buy_price)
    eval_amount = _int(qty * price)
    pl = eval_amount - buy_amount
    return {
        "id": str(h.get("id") or ""),
        "code": str(h.get("code") or ""),
        "name": str(h.get("name") or ""),
        "asset": str(h.get("asset") or ""),
        "pay": str(h.get("pay") or ""),
        "qty": qty,
        "buyPrice": buy_price,
        "price": price,
        "prevPrice": prev_price,
        "buyAmount": buy_amount,
        "evalAmount": eval_amount,
        "pl": pl,
        "retPct": round(_ratio(pl, buy_amount), 5),
        "dayPl": _int(qty * (price - prev_price)),
        "dayPct": round(_ratio(price - prev_price, prev_price), 5),
        "weight": 0.0,
        "memo": str(h.get("memo") or ""),
    }


def _prev_close(account: str, today: dt.date) -> tuple[int, str] | None:
    """전일대비의 기준 — history.csv 에서 오늘보다 이전인 가장 최근 마감 줄.

    '어제'가 아니라 '오늘보다 이전 중 가장 최근'인 이유: 주말·공휴일이 끼면
    어제 줄이 아예 없다. 마지막 기록과 비교해야 값이 비지 않는다.
    """
    day = str(today)
    rows = [r for r in store.read_history(account) if str(r.get("date") or "") < day]
    if not rows:
        return None
    last = max(rows, key=lambda r: str(r.get("date") or ""))
    return _int(last.get("total")), str(last.get("date") or "")


def snapshot(account: str) -> dict:
    """계좌 탭 하나가 이것만으로 그려진다 (SPEC §5). 상태를 저장하지 않는다."""
    state = store.load_state(account)
    today = today_kst()
    now = dt.datetime.now(KST).replace(tzinfo=None)

    items = [_item(h) for h in (state.get("holdings") or []) if isinstance(h, dict)]
    cash = _int(state.get("cash"))
    holdings_value = sum(i["evalAmount"] for i in items)
    buy_total = sum(i["buyAmount"] for i in items)
    total = holdings_value + cash
    eval_pl = holdings_value - buy_total
    for i in items:
        i["weight"] = round(_ratio(i["evalAmount"], total), 5)

    groups = []
    for key, label in PAY_GROUPS:
        gitems = [i for i in items if _group_key(i["pay"]) == key]
        gbuy = sum(i["buyAmount"] for i in gitems)
        geval = sum(i["evalAmount"] for i in gitems)
        groups.append({
            "key": key,
            "label": label,
            "items": gitems,
            "subtotal": {"buyAmount": gbuy, "evalAmount": geval,
                         "pl": geval - gbuy,
                         "retPct": round(_ratio(geval - gbuy, gbuy), 5),
                         "count": len(gitems)},
        })

    prev = _prev_close(account, today)
    if prev and prev[0] > 0:
        prev_total, prev_date = prev
        day_change = total - prev_total
        day_change_pct = round(_ratio(day_change, prev_total), 5)
        has_prev = True
    else:
        # 기록이 없을 때 0 을 적으면 '변동 없음'으로 읽혀 거짓말이 된다.
        # 프런트가 hasPrev 를 보고 '—' 를 그린다 (SPEC §7-1).
        prev_date, day_change, day_change_pct, has_prev = None, 0, 0.0, False

    divs = store.read_dividends(account)
    this_label, last_label = _month_label(today), _prev_month_label(today)
    this_div = sum(_int(d.get("amount")) for d in divs
                   if str(d.get("date") or "")[:7] == this_label)
    last_div = sum(_int(d.get("amount")) for d in divs
                   if str(d.get("date") or "")[:7] == last_label)

    start_date = state.get("startDate") or None
    return {
        "account": accounts.require(account),
        "accountLabel": accounts.label(account),
        "accountTitle": accounts.title(account),
        "today": str(today),
        "weekday": today.weekday(),
        "version": VERSION,
        "started": _is_started(start_date, today),
        "start_date": start_date,
        "priceUpdatedAt": state.get("priceUpdatedAt"),
        # 보유 종목이 없는 계좌(연금저축처럼 현금만 있는 경우)는 시세랄 게 없다.
        # 그대로 두면 첫 화면부터 '시세가 오래됐습니다' 경고가 계속 붙는다.
        "priceStale": bool(items) and _price_stale(state.get("priceUpdatedAt"), now),
        "totals": {
            "total": total,
            "holdingsValue": holdings_value,
            "cash": cash,
            "buyTotal": buy_total,
            "evalPl": eval_pl,
            "retPct": round(_ratio(eval_pl, buy_total), 5),
            "dayChange": day_change,
            "dayChangePct": day_change_pct,
            "hasPrev": has_prev,
            "prevDate": prev_date,
            "lastMonthLabel": last_label,
            "lastMonthDividend": last_div,
            "thisMonthLabel": this_label,
            "thisMonthDividend": this_div,
            "totalDividend": sum(_int(d.get("amount")) for d in divs),
        },
        "groups": groups,
        "strategy": state.get("strategy") or {"text": "", "updatedAt": None},
        # 이 앱에는 텔레그램이 없다. 화면이 이 키를 읽으므로 자리만 남긴다.
        "telegram_enabled": False,
        # 평일 자동 실행 시각. 설정 탭이 이 값을 그대로 보여준다 —
        # 화면에 "16:05" 를 박아 두면 config.yaml 을 바꿨을 때 화면만 거짓말을 한다.
        "dailyAt": _daily_at(),
    }


def _daily_at() -> str:
    try:
        import settings                                  # noqa: PLC0415
        cfg = settings.load()
        return f"{int(cfg.daily_hour):02d}:{int(cfg.daily_minute):02d}"
    except Exception:                                    # noqa: BLE001
        return "16:05"


def _is_started(start_date, today: dt.date) -> bool:
    """시작일을 정하지 않았으면 이미 굴리고 있는 계좌로 본다.

    이 앱은 이미 가진 보유 종목을 기록하는 앱이라, 시작일을 정하지 않아도
    첫 실행부터 바로 쓸 수 있어야 한다.
    """
    if not start_date:
        return True
    try:
        return today >= dt.date.fromisoformat(str(start_date))
    except ValueError:
        return True


# ---------------------------------------------------------------------------
# 성과 탭 — 기록 원천
# ---------------------------------------------------------------------------
def _numify(rows: list, int_cols: tuple, float_cols: tuple = ()) -> list:
    """CSV 는 전부 문자열로 읽힌다. 그래프가 바로 쓸 수 있게 숫자로 바꿔 보낸다.

    빈칸은 빈칸으로 둔다 (현금·배당 줄에는 수량·단가가 없다).
    """
    out = []
    for r in rows:
        d = dict(r)
        for c in int_cols:
            if str(d.get(c, "")).strip() != "":
                d[c] = _int(d.get(c))
        for c in float_cols:
            if str(d.get(c, "")).strip() != "":
                d[c] = round(_num(d.get(c)), 6)
        out.append(d)
    return out


def history(account: str, days: int = 180) -> dict:
    """성과 탭 한 벌. 체결 이력은 최근 100건만 보낸다 (모바일에서 길면 못 본다)."""
    rows = sorted(store.read_history(account), key=lambda r: str(r.get("date") or ""))
    if days and days > 0:
        # '최근 N일' 이지 '마지막 N행' 이 아니다. 주말·휴장일이 섞여 기록이 매일
        # 쌓이지 않으므로 행 수로 자르면 실제로는 훨씬 먼 과거까지 딸려 온다.
        cutoff = str(today_kst() - dt.timedelta(days=days))
        rows = [r for r in rows if str(r.get("date") or "") >= cutoff]
    # 운용 시작일 이전의 일별 기록은 성과에 넣지 않는다 (2026-09-18 사용자 요청: "성과는 오늘부터").
    # 지우지 않고 가리기만 한다 — 관리에서 시작일을 비우면 예전 기록이 그대로 돌아온다.
    # 배당·체결 이력은 가리지 않는다. 일별 스냅샷이 아니라 실제로 일어난 입출금 기록이고,
    # 월 배당 막대는 그 달 전체를 보여줘야 해서다(9월 초 배당과 9/17 배당이 한 달로 묶인다).
    start = str(store.load_state(account).get("startDate") or "")
    if start:
        rows = [r for r in rows if str(r.get("date") or "") >= start]
    trades = sorted(store.read_trades(account), key=lambda r: str(r.get("ts") or ""))
    divs = sorted(store.read_dividends(account), key=lambda r: str(r.get("date") or ""))
    return {
        "history": _numify(rows, ("total", "buyTotal", "evalPl", "cash",
                                  "holdingsValue", "midValue", "endValue",
                                  "etcValue", "divMonth"), ("retPct",)),
        "trades": _numify(trades[-100:], ("qty", "price", "amount")),
        "dividends": _numify(divs, ("amount",)),
    }


# ---------------------------------------------------------------------------
# 보유 종목 CRUD
# ---------------------------------------------------------------------------
def _locked(fn):
    """상태를 바꾸는 함수를 store 의 잠금으로 감싼다.

    평일 16:05 스케줄러와 사용자 요청이 서로 다른 스레드라, 잠그지 않으면
    읽기→고치기→쓰기 사이에 끼어들어 방금 입력한 체결이 조용히 사라진다.
    바꾸지 않고 읽기만 하는 snapshot()/history() 에는 걸지 않는다 — 읽기는
    어차피 한 번의 load_state() 로 끝나고, 잠그면 조회가 갱신을 기다리게 된다.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with store.state_lock():
            return fn(*args, **kwargs)
    return wrapper


def _find(holdings: list, hid: str) -> dict | None:
    return next((h for h in holdings if str(h.get("id") or "") == hid), None)


# 같은 종목·같은 매수(매도)·같은 수량·같은 단가가 이 시간 안에 또 들어오면 한 번 되묻는다.
# 2026-09-13 에 같은 매수(1,106주 @12,585)가 2분 간격으로 두 번 저장돼 보유수량이 부풀었다.
# 버튼 연타만이 아니라 시트를 다시 열어 같은 값을 넣는 경우까지 잡으려고, 화면이 아니라
# 서버에서 trades.csv 를 보고 판정한다. 정말 두 번 산 거라면 확인 한 번으로 그대로 들어간다.
DUP_WINDOW_MIN = 10


def _recent_duplicate(account: str, action: str, code: str, qty: int, price: int) -> int | None:
    """방금 같은 체결이 기록됐으면 몇 분 전인지 돌려준다. 없으면 None."""
    now = dt.datetime.now(KST).replace(tzinfo=None)
    for r in reversed(store.read_trades(account)):          # 뒤에서부터 = 최근 것부터
        try:
            ts = dt.datetime.fromisoformat(str(r.get("ts") or ""))
        except ValueError:
            continue
        if ts.tzinfo is not None:
            ts = ts.astimezone(KST).replace(tzinfo=None)
        age = now - ts
        if age > dt.timedelta(minutes=DUP_WINDOW_MIN):
            break                                    # 기록은 시간순이라 더 볼 필요가 없다
        if age < dt.timedelta(0):
            continue
        if (str(r.get("action")) == action and str(r.get("code")) == code
                and _int(r.get("qty")) == qty and _int(r.get("price")) == price):
            return int(age.total_seconds() // 60)
    return None


def _dup_message(kind: str, name: str, qty: int, price: int, mins: int) -> str:
    when = "방금" if mins < 1 else f"{mins}분 전에"
    return (f"중복 확인: {when} 같은 {kind}({name} {qty:,}주 · {price:,}원)가 이미 기록됐습니다. "
            f"한 번 더 반영할까요?")


def _log_trade(account: str, action: str, h: dict, qty, price, amount, note: str = "") -> None:
    """종목 시트에서 일어난 변경을 trades.csv 에 한 줄 남긴다.

    되돌리기용이 아니라 기록용이다. 시세 갱신은 남기지 않는다 —
    action 라벨에 자리가 없고, 매일 종목 수만큼 쌓이면 체결 이력이 묻힌다.
    """
    store.append_trade(account, {
        "ts": _now_iso(),                 # 중복 입력 판정이 이 시각을 보므로 KST 로 못박는다
        "date": str(today_kst()),
        "action": action,
        "code": str(h.get("code") or ""),
        "name": str(h.get("name") or ""),
        "qty": qty,
        "price": price,
        "amount": amount,
        "note": note,
    })


@_locked
def save_holding(account: str, body: dict) -> dict:
    """종목 시트에서 온 한 건을 반영한다 (SPEC §6).

    id 가 없으면 신규 추가, 있으면 그 종목 수정이다.
    action 이 buy/sell 이면 deltaQty 주를 deltaPrice 에 체결한 것으로 보고
    수량·평균단가를 다시 계산한다. edit 이면 보낸 값을 최종값으로 덮어쓴다.
    """
    state = store.load_state(account)
    holdings = state.setdefault("holdings", [])
    today = str(today_kst())

    hid = str(body.get("id") or "").strip()
    cur = _find(holdings, hid) if hid else None
    if hid and cur is None:
        raise ValueError("해당 종목을 찾을 수 없습니다. 화면을 새로 고친 뒤 다시 시도해주세요.")

    action = str(body.get("action") or "edit").strip().lower()
    price = _int(body.get("price"))
    delta_qty = _int(body.get("deltaQty"))
    delta_price = _int(body.get("deltaPrice"))

    # 오타 가드 — 기존 현재가와 30% 넘게 벌어지면 되묻는다.
    # 신규 추가에는 비교할 기존 값이 없으므로 적용하지 않는다.
    if cur is not None and price > 0:
        old_price = _int(cur.get("price"))
        if old_price > 0 and abs(price - old_price) / old_price > PRICE_SANITY_GAP \
                and not body.get("confirm_price"):
            raise ValueError(f"현재가가 기존 {old_price:,}원과 30% 이상 차이납니다. "
                             f"확인 후 다시 보내주세요.")

    # ---- 신규 추가 -------------------------------------------------------
    if cur is None:
        code = str(body.get("code") or "").strip()
        name = str(body.get("name") or "").strip()
        code_re, code_msg = _code_rule(account)
        if not code_re.match(code):
            raise ValueError(code_msg)
        if not name:
            raise ValueError("종목명을 넣어주세요.")
        qty = _int(body.get("qty"))
        buy_price = _int(body.get("buyPrice"))
        if qty < 0:
            raise ValueError("수량은 0주 이상이어야 합니다.")
        # 매수단가가 음수면 매수금액이 음수가 되어 그룹 소계와 수익률이 통째로 뒤집힌다.
        if buy_price < 0 or price < 0:
            raise ValueError("금액은 0원 이상이어야 합니다.")
        px = price or buy_price          # 현재가를 안 적었으면 매수단가로 시작한다
        h = {"id": store.new_holding_id(), "code": code.upper(), "name": name,
             "asset": str(body.get("asset") or "").strip(),
             "pay": _norm_pay(body.get("pay")),
             "qty": qty, "buyPrice": buy_price,
             "price": px, "prevPrice": px, "priceDate": today,
             "memo": str(body.get("memo") or "").strip()}
        holdings.append(h)
        store.save_state(account, state)
        _log_trade(account, "add", h, qty, px, _int(qty * px), "종목 추가")
        return {"ok": True, "id": h["id"],
                "message": f"{name} 종목을 추가했습니다."}

    name = str(cur.get("name") or "")

    # ---- 매수 — 가중평균 단가를 다시 계산한다 -----------------------------
    if action == "buy":
        if delta_qty <= 0:
            raise ValueError("매수 수량을 넣어주세요.")
        if delta_price <= 0:
            raise ValueError("체결단가를 넣어주세요.")
        if not body.get("confirm_dup"):
            mins = _recent_duplicate(account, "buy", str(cur.get("code") or ""), delta_qty, delta_price)
            if mins is not None:
                raise ValueError(_dup_message("매수", name, delta_qty, delta_price, mins))
        old_qty, old_buy = _int(cur.get("qty")), _int(cur.get("buyPrice"))
        new_qty = old_qty + delta_qty
        new_buy = _int((old_qty * old_buy + delta_qty * delta_price) / new_qty)
        cur["qty"], cur["buyPrice"] = new_qty, new_buy
        if price > 0:
            _apply_price(cur, price, today)
        store.save_state(account, state)
        _log_trade(account, "buy", cur, delta_qty, delta_price,
                   _int(delta_qty * delta_price), f"보유 {new_qty:,}주")
        return {"ok": True, "id": cur["id"],
                "message": f"{name} {delta_qty:,}주를 {delta_price:,}원에 매수 반영했습니다. "
                           f"보유 {new_qty:,}주 · 평균단가 {new_buy:,}원"}

    # ---- 매도 — 평균단가는 그대로 두고 실현손익만 남긴다 -------------------
    if action == "sell":
        if delta_qty <= 0:
            raise ValueError("매도 수량을 넣어주세요.")
        if delta_price <= 0:
            raise ValueError("체결단가를 넣어주세요.")
        old_qty, old_buy = _int(cur.get("qty")), _int(cur.get("buyPrice"))
        if delta_qty > old_qty:
            raise ValueError(f"보유 수량은 {old_qty:,}주입니다. 그보다 많이 팔 수 없습니다.")
        if not body.get("confirm_dup"):
            mins = _recent_duplicate(account, "sell", str(cur.get("code") or ""), delta_qty, delta_price)
            if mins is not None:
                raise ValueError(_dup_message("매도", name, delta_qty, delta_price, mins))
        new_qty = old_qty - delta_qty
        pnl = _int((delta_price - old_buy) * delta_qty)
        # 매도는 평균단가를 바꾸지 않는다. 남은 수량의 취득원가는 그대로다.
        cur["qty"] = new_qty
        if price > 0:
            _apply_price(cur, price, today)
        store.save_state(account, state)
        # amount 칸에 체결금액이 아니라 실현손익을 적는다 (SPEC §6).
        _log_trade(account, "sell", cur, delta_qty, delta_price, pnl,
                   f"체결금액 {_int(delta_qty * delta_price):,}원 · 잔여 {new_qty:,}주")
        msg = (f"{name} {delta_qty:,}주를 {delta_price:,}원에 매도 반영했습니다. "
               f"실현손익 {pnl:+,}원 · 남은 수량 {new_qty:,}주")
        if new_qty == 0:
            # 0주가 되어도 종목을 지우지 않는다 (SPEC §6). 다시 살 수 있고,
            # 이력을 남긴 종목이 목록에서 사라지면 배당 입력에서도 못 고른다.
            msg += " (0주로 남겨 두었습니다. 목록에서 빼려면 삭제를 눌러주세요.)"
        return {"ok": True, "id": cur["id"], "message": msg}

    # ---- 직접 수정 — 보낸 값을 최종값으로 덮어쓴다 -------------------------
    code = str(body.get("code") or cur.get("code") or "").strip()
    code_re, code_msg = _code_rule(account)
    if not code_re.match(code):
        raise ValueError(code_msg)
    qty = _int(body.get("qty"))
    if qty < 0:
        raise ValueError("수량은 0주 이상이어야 합니다.")
    buy_price = _int(body.get("buyPrice"))
    if buy_price < 0 or price < 0:
        raise ValueError("금액은 0원 이상이어야 합니다.")
    cur["code"] = code.upper()
    cur["name"] = str(body.get("name") or name).strip() or name
    # 자산군은 비워 보내오면 원래 값을 지킨다. 요약 표에서 종목명 밑에 붙는 값이라
    # 시트가 빠뜨린 한 번의 저장으로 지워지면 눈에 띄게 허전해진다.
    cur["asset"] = str(body.get("asset") or cur.get("asset") or "").strip()
    # pay 는 "기타" 를 빈 문자열로 표현하므로 '안 보냄' 과 '기타로 바꿔달라' 를
    # 구분해야 한다. 키 자체가 없으면 기존 배당시기를 지킨다 — 그러지 않으면
    # pay 를 빠뜨린 저장 한 번에 월중/월말 종목이 조용히 기타로 옮겨간다.
    cur["pay"] = _norm_pay(body.get("pay")) if "pay" in body else cur.get("pay", "")
    cur["qty"] = qty
    cur["buyPrice"] = buy_price
    cur["memo"] = str(body.get("memo") or "").strip()
    if price > 0:
        _apply_price(cur, price, today)
    store.save_state(account, state)
    _log_trade(account, "edit", cur, qty, _int(cur.get("price")),
               _int(qty * _int(cur.get("price"))), "직접 수정")
    return {"ok": True, "id": cur["id"],
            "message": f"{cur['name']} 정보를 수정했습니다."}


@_locked
def delete_holding(account: str, hid: str) -> dict:
    """종목을 목록에서 지운다. 지운 기록은 trades.csv 에 remove 로 남는다."""
    state = store.load_state(account)
    holdings = state.get("holdings") or []
    h = _find(holdings, str(hid or "").strip())
    if h is None:
        raise ValueError("해당 종목을 찾을 수 없습니다. 화면을 새로 고친 뒤 다시 시도해주세요.")
    state["holdings"] = [x for x in holdings if x is not h]
    store.save_state(account, state)
    qty, price = _int(h.get("qty")), _int(h.get("price"))
    _log_trade(account, "remove", h, qty, price, _int(qty * price), "종목 삭제")
    return {"ok": True,
            "message": f"{h.get('name') or h.get('code')} 종목을 목록에서 지웠습니다."}


# ---------------------------------------------------------------------------
# 시세
# ---------------------------------------------------------------------------
@_locked
def set_prices(account: str, prices: dict) -> dict:
    """현재가 일괄 입력. 장중에 손으로 훑어 넣는 용도다 (SPEC §7-1 「관리」).

    빈칸이나 0 은 건너뛴다 — 안 적은 종목의 평가금액이 0 이 되면 총금액이 무너진다.
    """
    state = store.load_state(account)
    holdings = state.get("holdings") or []
    today = str(today_kst())
    updated = 0
    for hid, raw in (prices or {}).items():
        h = _find(holdings, str(hid))
        if h is None:
            continue
        px = _int(raw)
        if px <= 0:
            continue
        _apply_price(h, px, today)
        updated += 1
    if updated:
        state["priceUpdatedAt"] = _now_iso()
        store.save_state(account, state)
        msg = f"{updated}종목의 현재가를 반영했습니다."
    else:
        msg = "반영할 현재가가 없습니다. 숫자를 넣고 다시 눌러주세요."
    return {"ok": True, "message": msg, "updated": updated}


@_locked
def refresh_prices(account: str) -> dict:
    """KIS 시세로 현재가를 자동 갱신한다 (SPEC §4 /api/refresh-prices).

    시세 모듈은 여기서만 늦게 불러온다. KIS 키가 없거나 네트워크가 막혀도
    요약·체결 화면은 그대로 떠 있어야 하기 때문이다.
    저장은 store 를 쥔 이쪽에서만 한다 (market 은 넘겨받은 dict 만 고친다).
    """
    if not accounts.auto_price(account):
        # KIS 가 모르는 계좌(autoPrice=False). 부르면 종목마다 실패로 돌아오고
        # 평일마다 '시세를 받지 못했습니다' 알림만 울린다. 아예 시도하지 않는다.
        return {"ok": True, "updated": 0, "failed": [],
                "message": "이 계좌는 시세 자동갱신을 쓰지 않습니다. 현재가를 직접 넣어주세요."}
    state = store.load_state(account)
    try:
        import market                                     # noqa: PLC0415
        r = market.refresh_prices(state) or {}
    except Exception as e:  # noqa: BLE001
        log.exception("시세 갱신 실패")
        return {"ok": False, "updated": 0, "failed": [],
                "message": f"시세를 갱신하지 못했습니다. 현재가는 손으로 넣어주세요. ({type(e).__name__})"}
    updated = _int(r.get("updated"))
    if updated:
        store.save_state(account, state)
    return {"ok": bool(r.get("ok")),
            "message": str(r.get("message") or ""),
            "updated": updated,
            "failed": list(r.get("failed") or [])}


# ---------------------------------------------------------------------------
# 현금 · 배당 · 전략 메모
# ---------------------------------------------------------------------------
@_locked
def set_cash(account: str, amount) -> dict:
    state = store.load_state(account)
    before = _int(state.get("cash"))
    cash = _int(amount)
    if cash < 0:
        raise ValueError("현금은 0원 이상이어야 합니다.")
    state["cash"] = cash
    store.save_state(account, state)
    _log_trade(account, "cash", {"code": "", "name": "현금"}, "", "", cash,
               f"{before:,}원 → {cash:,}원")
    return {"ok": True, "message": f"현금을 {cash:,}원으로 수정했습니다."}


@_locked
def add_dividend(account: str, code: str, name: str, amount, date: str | None = None) -> dict:
    """배당 입금을 기록한다. 현금은 건드리지 않는다 —
    실제 입금은 증권사가 하고, 이 앱은 그 사실을 적어둘 뿐이다."""
    amt = _int(amount)
    if amt <= 0:
        raise ValueError("배당금은 1원 이상으로 넣어주세요.")
    day = str(date or "").strip() or str(today_kst())
    try:
        day = str(dt.date.fromisoformat(day))
    except ValueError:
        raise ValueError("날짜 형식은 YYYY-MM-DD 입니다.")

    code = str(code or "").strip()
    name = str(name or "").strip()
    if not name and code:
        # 종목명을 안 보내왔으면 보유 목록에서 찾아 채운다 (기록이 코드만 남으면 못 읽는다).
        state = store.load_state(account)
        hit = next((h for h in (state.get("holdings") or [])
                    if str(h.get("code") or "") == code), None)
        name = str(hit.get("name") or "") if hit else ""
    if not code and not name:
        raise ValueError("배당을 받은 종목을 골라주세요.")

    store.append_dividend(account, {"date": day, "code": code, "name": name, "amount": amt})
    _log_trade(account, "dividend", {"code": code, "name": name}, "", "", amt, f"{day} 지급")
    return {"ok": True, "message": f"{name or code} 배당 {amt:,}원을 기록했습니다."}


@_locked
def set_strategy(account: str, text: str) -> dict:
    """내일의 전략 메모. 자동저장이 아니라 저장 버튼을 눌렀을 때만 여기로 온다."""
    state = store.load_state(account)
    state["strategy"] = {"text": str(text or ""), "updatedAt": _now_iso()}
    store.save_state(account, state)
    return {"ok": True, "message": "전략 메모를 저장했습니다."}


# ---------------------------------------------------------------------------
# 마감 저장 · 시작일
# ---------------------------------------------------------------------------
@_locked
def close_today(account: str) -> dict:
    """오늘 마감을 history.csv 에 남긴다 (성과 탭이 여기서 자란다).

    같은 날짜가 이미 있으면 store 가 덮어쓰므로 하루에 여러 번 눌러도 안전하다.
    """
    import daily_close                                    # noqa: PLC0415

    snap = snapshot(account)
    totals = snap["totals"]
    if totals["total"] <= 0:
        # 시세를 못 받아 총금액이 0 인 날을 남기면 성과 그래프가 통째로 튄다.
        raise ValueError("총금액이 0원이라 저장하지 않았습니다. 현재가를 먼저 넣어주세요.")
    row = daily_close.build_row(totals, snap["groups"], snap["today"])
    store.upsert_history_row(account, row)
    return {"ok": True,
            "message": f"{snap['today']} 마감을 저장했습니다. "
                       f"(총금액 {totals['total']:,}원)"}


@_locked
def set_start_date(account: str, date_str: str | None) -> dict:
    """운용 시작일. 이 날짜 전에는 평일 자동 마감 기록을 건너뛴다. 비우면 바로 운용 중으로 본다."""
    state = store.load_state(account)
    if date_str:
        d = dt.date.fromisoformat(str(date_str).strip())   # 형식 검증 (틀리면 400)
        state["startDate"] = str(d)
        store.save_state(account, state)
        return {"ok": True, "start_date": str(d),
                "message": f"{d} 부터 운용한 것으로 기록합니다."}
    state["startDate"] = None
    store.save_state(account, state)
    return {"ok": True, "start_date": None,
            "message": "시작일을 지웠습니다. 바로 운용 중으로 봅니다."}
