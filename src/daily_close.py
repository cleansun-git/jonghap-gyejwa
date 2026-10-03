# -*- coding: utf-8 -*-
"""그날 마감 스냅샷을 data/<계좌>/history.csv 에 한 줄로 남긴다 (성과 탭의 원천).

  build_row() 는 이미 계산이 끝난 값만 받아 CSV 한 줄을 만드는 순수 함수다.
  시세도 파일도 건드리지 않으므로 web/service.py 가 스냅샷을 만든 그 자리에서
  바로 불러 쓸 수 있고, 계산이 어디서 왔는지 헷갈릴 일이 없다.

  같은 날짜를 덮어쓰는 일은 store.upsert_history_row() 가 맡는다
  (하루에 여러 번 저장해도 안전 — SPEC §2).

휴장일 판단은 여기서 하지 않는다. 스케줄러가 부르기 전에 market.is_market_open()
으로 이미 걸러내고(2026-09-16), 사람이 계좌 탭 「관리 > 오늘 마감 저장」으로 부를 때는
일부러 누른 것이므로 그대로 저장한다. 같은 날짜는 덮어써지므로 한 줄 더 남아도 해가 없다.
"""
from __future__ import annotations

import datetime as dt
import logging

log = logging.getLogger(__name__)

# 서버가 UTC 로 돌아도 '오늘'은 한국 장 기준이어야 한다.
KST = dt.timezone(dt.timedelta(hours=9))

# SPEC §2 의 history.csv 헤더 순서 그대로. build_row 는 이 순서로 dict 를 만든다
# (파이썬 dict 는 넣은 순서를 지키므로 store 가 그대로 써도 컬럼이 어긋나지 않는다).
ROW_COLS = ["date", "total", "buyTotal", "evalPl", "retPct", "cash",
            "holdingsValue", "midValue", "endValue", "etcValue",
            "divMonth", "savedAt"]

# 그룹 키 → history 컬럼. 그룹은 항상 이 셋뿐이다 (SPEC §5).
GROUP_COLS = {"월중": "midValue", "월말": "endValue", "기타": "etcValue"}


def _int(value) -> int:
    """금액은 정수 원 단위. 숫자로 못 읽는 값은 0 (CSV 에 빈칸이 남지 않게)."""
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _month_dividend(totals: dict, date_str: str) -> int:
    """그 날짜가 속한 달의 배당 합계 (SPEC §2).

    스냅샷이 이미 이번달·지난달 합계를 들고 있으므로 dividends.csv 를 다시 읽지 않는다.
    지난 날짜로 마감을 다시 만들 때처럼 어느 쪽 달과도 안 맞으면 0 으로 둔다 —
    엉뚱한 달의 합계를 적는 것보다 비워두는 편이 낫다.
    """
    month = date_str[:7]
    if str(totals.get("thisMonthLabel") or "") == month:
        return _int(totals.get("thisMonthDividend"))
    if str(totals.get("lastMonthLabel") or "") == month:
        return _int(totals.get("lastMonthDividend"))
    return 0


def build_row(snapshot_totals: dict, groups: list, today) -> dict:
    """마감 한 줄을 만든다. 계산은 하지 않고 이미 나온 값을 옮겨 담기만 한다.

    snapshot_totals · groups 는 SNAPSHOT 응답(SPEC §5)의 totals · groups 를 그대로 받는다.
    today 는 date 객체든 "YYYY-MM-DD" 문자열이든 상관없다.
    """
    totals = snapshot_totals or {}
    date_str = str(today)[:10]

    row = {
        "date": date_str,
        "total": _int(totals.get("total")),
        "buyTotal": _int(totals.get("buyTotal")),
        "evalPl": _int(totals.get("evalPl")),
        # retPct 는 화면과 같은 소수로 남긴다 (-0.0389 = -3.89%). 성과 탭이 ×100 한다.
        "retPct": round(_num(totals.get("retPct")), 6),
        "cash": _int(totals.get("cash")),
        "holdingsValue": _int(totals.get("holdingsValue")),
        # 그룹 소계는 아래에서 채운다. 종목이 없는 그룹도 0 으로 남아야 컬럼이 밀리지 않는다.
        "midValue": 0,
        "endValue": 0,
        "etcValue": 0,
        "divMonth": _month_dividend(totals, date_str),
        "savedAt": dt.datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S"),
    }

    for g in (groups or []):
        g = g or {}
        col = GROUP_COLS.get(str(g.get("key") or ""))
        if col:
            row[col] = _int((g.get("subtotal") or {}).get("evalAmount"))
    return row


def close_today(account: str) -> dict:
    """그 계좌의 오늘 스냅샷을 history.csv 에 저장한다. 반환: {"ok", "message"}

    service 를 파일 맨 위에서 import 하지 않는 이유: service.py 가 build_row 를
    가져다 쓰므로 서로 물린다(순환 import). 부를 때만 늦게 불러온다.
    """
    try:
        import service
        import store
    except ImportError as e:
        log.warning("마감 저장 준비 실패: %s", e)
        return {"ok": False, "message": "마감을 저장하지 못했습니다. 잠시 후 다시 시도해주세요."}

    snap_fn = getattr(service, "snapshot", None)
    if snap_fn is None:
        return {"ok": False, "message": "마감을 저장하지 못했습니다. (스냅샷 계산을 찾을 수 없습니다)"}

    try:
        snap = snap_fn(account) or {}
        totals = snap.get("totals") or {}
        # 스냅샷이 이미 정한 '오늘'을 그대로 쓴다. 화면에 보이는 날짜와 기록이 달라지면 안 된다.
        today = str(snap.get("today") or dt.datetime.now(KST).date())
        # 시세를 못 받아 총금액이 0 으로 계산된 날을 남기면 성과 그래프가 통째로 튄다.
        if _int(totals.get("total")) <= 0:
            return {"ok": False, "message": "총금액이 0원이라 마감을 저장하지 않았습니다."}

        row = build_row(totals, snap.get("groups") or [], today)
        store.upsert_history_row(account, row)
    except Exception as e:  # noqa: BLE001 - 마감 실패가 스케줄러 전체를 죽이면 안 된다
        log.exception("마감 저장 실패")
        return {"ok": False, "message": f"마감 저장에 실패했습니다: {e}"}

    return {"ok": True,
            "message": f"{row['date']} 마감을 저장했습니다. (총금액 {row['total']:,}원)"}
