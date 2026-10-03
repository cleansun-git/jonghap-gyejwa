# -*- coding: utf-8 -*-
"""상태/이력 저장소 — 계좌마다 폴더 하나.

  data/<계좌>/state.json        현재 보유 종목·현금·전략 메모
  data/<계좌>/history.csv       일별 마감 스냅샷 (성과 탭 원천)
  data/<계좌>/trades.csv        체결·변경 이력 (기록용, 되돌리기용이 아니다)
  data/<계좌>/dividends.csv     배당 입금 내역

  data/.kis_token_cache.json    KIS 토큰 (계좌와 무관 — 하나를 돌려 쓴다)
  data/push_subs.json           알림 구독 (계좌와 무관)

계좌를 파일로 완전히 갈라놓은 이유(2026-09-16 ISA 추가):
한 파일에 계좌 칸을 더하는 쪽이 합계를 내기는 쉽지만, 이미 쌓인 퇴직연금 기록의
형식을 바꿔야 한다. 기록이 사용자의 실제 자산 이력이라 옮기다 깨지는 위험을 지지 않았다.
합계는 폴더 몇 개를 더 읽어 더하면 된다.

state.json 이 없으면 SEED[계좌] 로 처음 한 벌을 만들어 준다.
빈 화면 대신 실제 보유 종목이 바로 보이게 하려는 것이다.

**모든 저장/조회 함수는 계좌를 첫 인자로 반드시 받는다.** 기본값을 두지 않는 이유:
기본값이 있으면 계좌를 빠뜨린 호출이 조용히 퇴직연금 파일을 읽고 쓴다.
없으면 TypeError 로 그 자리에서 터진다 — 데이터가 섞이는 것보다 낫다.
"""
from __future__ import annotations

import contextlib
import csv
import datetime as dt
import json
import logging
import os
import random
import shutil
import threading
import time

import accounts
from settings import DATA_DIR

# 상태 파일을 바꾸는 모든 경로가 공유하는 잠금 (state_lock 참고).
# 계좌별로 나누지 않는다 — 계좌가 몇 개 안 되고, 한 번에 한 요청만 처리하면 충분하다.
_STATE_LOCK = threading.RLock()

log = logging.getLogger(__name__)

# 계좌와 무관한 파일(토큰·구독)은 예전처럼 data/ 바로 아래에 둔다.
LEGACY_FILES = ("state.json", "history.csv", "trades.csv", "dividends.csv",
                "state.json.bak")


def account_dir(account: str) -> str:
    """계좌 폴더. 등록부에 없는 계좌는 여기서 막힌다(경로 조작 방지)."""
    return os.path.join(DATA_DIR, accounts.require(account))


def _p(account: str, name: str) -> str:
    _migrate_legacy_once()
    return os.path.join(account_dir(account), name)


def state_path(account: str) -> str:
    return _p(account, "state.json")


_migrated = False


def _migrate_legacy_once() -> None:
    """예전 구조(data/state.json)를 data/dc/ 로 한 번 옮긴다.

    ISA 를 붙이기 전에 쌓인 퇴직연금 기록이 여기 해당한다. 옮기기 전에
    data/_backup_before_accounts/ 에 통째로 복사해 둔다 — 실수했을 때
    되돌릴 수 있어야 하는 유일한 데이터다.
    """
    global _migrated
    if _migrated:
        return
    with _STATE_LOCK:
        if _migrated:
            return
        _migrated = True                       # 실패해도 매 호출마다 다시 시도하지는 않는다
        legacy = os.path.join(DATA_DIR, "state.json")
        target_dir = os.path.join(DATA_DIR, accounts.DEFAULT)
        if not os.path.exists(legacy) or os.path.exists(os.path.join(target_dir, "state.json")):
            return
        try:
            backup = os.path.join(DATA_DIR, "_backup_before_accounts")
            os.makedirs(backup, exist_ok=True)
            os.makedirs(target_dir, exist_ok=True)
            moved = []
            for name in LEGACY_FILES:
                src = os.path.join(DATA_DIR, name)
                if not os.path.exists(src):
                    continue
                _safe_backup(src, os.path.join(backup, name))
                shutil.move(src, os.path.join(target_dir, name))
                moved.append(name)
            log.info("기존 데이터를 data/%s/ 로 옮겼습니다: %s (사본: %s)",
                     accounts.DEFAULT, ", ".join(moved), backup)
        except OSError as e:
            log.exception("데이터 이전 실패 — 예전 위치를 그대로 둡니다 (%s)", e)

HISTORY_COLS = ["date", "total", "buyTotal", "evalPl", "retPct", "cash",
                "holdingsValue", "midValue", "endValue", "etcValue",
                "divMonth", "savedAt"]
TRADE_COLS = ["ts", "date", "action", "code", "name", "qty", "price",
              "amount", "note"]
DIVIDEND_COLS = ["date", "code", "name", "amount", "ts"]


# ---------------------------------------------------------------------------
# 시드 데이터 — 배포형 샘플이다. 실제 보유가 아니다.
#   종목당 평가금액을 100만원에 맞췄다(qty = round(1,000,000 / price)).
#   금액이 전부 떨어지는 숫자여서 받는 사람이 데모 데이터임을 바로 알아본다.
#   매수단가는 현재가에서 ±3% 로 엇갈리게 넣었다 — 손익에 빨강(수익)과
#   파랑(손실)이 둘 다 보여야 색 규칙이 첫 화면에서 드러난다.
#
# 이 앱은 KIS 시세 자동 갱신을 쓰지 않는다(accounts.py 의 autoPrice=False).
# 현재가는 받는 사람이 손으로 넣는다. 아래 price 는 그 출발점일 뿐이다.
#
# 시드는 '첫 화면이 비어 있지 않게' 하는 용도다. 자기 계좌로 쓸 사람은 증권사
# 잔고를 보고 수량·매수단가·현금을 자기 값으로 고쳐야 한다.
# ---------------------------------------------------------------------------
SEED_PRICE_DATE = "2026-10-01"
SEED_PRICE_UPDATED_AT = "2026-10-01T16:00:00"
SEED_CASH = 1_000_000

SEED_HOLDINGS = [
    {"id": "h1", "code": "441640", "name": "KODEX 미국배당커버드콜액티브",
     "asset": "선진국주식", "pay": "월중", "qty": 81, "buyPrice": 11920, "price": 12280},
    {"id": "h2", "code": "493810", "name": "TIGER 미국AI빅테크10타겟데일리커버드콜",
     "asset": "선진국주식", "pay": "월중", "qty": 90, "buyPrice": 11460, "price": 11115},
    {"id": "h3", "code": "498400", "name": "KODEX 200타겟위클리커버드콜",
     "asset": "국내주식", "pay": "월중", "qty": 47, "buyPrice": 20560, "price": 21180},
    {"id": "h4", "code": "498410", "name": "KODEX 금융고배당TOP10타겟위클리커버드콜",
     "asset": "국내주식", "pay": "월말", "qty": 86, "buyPrice": 12060, "price": 11695},
    {"id": "h5", "code": "0219E0", "name": "KODEX 200커버드콜액티브",
     "asset": "국내주식", "pay": "월말", "qty": 116, "buyPrice": 8370, "price": 8620},
    # 0040Y0·0013R0 은 이름이 채권혼합이지만 평가손익을 움직이는 것은 팔란티어·테슬라
    # 주가다. 그래서 자산군을 해외채권이 아니라 선진국주식으로 둔다.
    {"id": "h6", "code": "0040Y0", "name": "SOL 팔란티어커버드콜OTM채권혼합",
     "asset": "선진국주식", "pay": "월말", "qty": 127, "buyPrice": 8100, "price": 7855},
    {"id": "h7", "code": "0013R0", "name": "RISE 테슬라미국채타겟커버드콜혼합(합성)",
     "asset": "선진국주식", "pay": "월말", "qty": 131, "buyPrice": 7390, "price": 7615},
    {"id": "h8", "code": "494300", "name": "KODEX 미국나스닥100데일리커버드콜OTM",
     "asset": "선진국주식", "pay": "월말", "qty": 115, "buyPrice": 8990, "price": 8720},
    # 배당이 없는 종목은 pay 를 빈 문자열로 둔다 (= 기타 그룹).
    {"id": "h9", "code": "361580", "name": "RISE 200TR",
     "asset": "국내주식", "pay": "", "qty": 16, "buyPrice": 61850, "price": 63710},
]

# 시드 배당. 퇴직연금 탭의 '월 배당' KPI 가 첫 실행부터 값이 있게 한다.
# 금액도 떨어지는 숫자로 둬서 샘플임이 드러나게 했다.
SEED_DIVIDEND_DATE = "2026-10-02"
SEED_DIVIDENDS = [
    {"code": "0219E0", "name": "KODEX 200커버드콜액티브", "amount": 10000},
    {"code": "498410", "name": "KODEX 금융고배당TOP10타겟위클리커버드콜", "amount": 8000},
]

# ISA — 보유 종목을 비워 둔다. 받는 사람이 「종목 추가」로 자기 종목을 넣어 보는 것이
# 배포형답고, 그 과정에서 빈 계좌 화면도 함께 확인된다. 현금만 넣어 둔다.
# 보유가 없으니 시세 날짜도 없다(SEED 에서 priceDate=None).
SEED_ISA_CASH = 1_000_000

# 연금저축·IRP·일반 — 현금만. 보유 종목은 앱에서 「종목 추가」로 넣는다.
SEED_PEN_CASH = 1_000_000
SEED_IRP_CASH = 1_000_000
SEED_GEN_CASH = 1_000_000

# 계좌별 시드 한 벌. 새 계좌를 더할 때 여기에 한 줄 더한다.
SEED = {
    "dc": {"holdings": SEED_HOLDINGS, "cash": SEED_CASH,
           "priceDate": SEED_PRICE_DATE, "priceUpdatedAt": SEED_PRICE_UPDATED_AT,
           "dividends": SEED_DIVIDENDS, "dividendDate": SEED_DIVIDEND_DATE},
    "isa": {"holdings": [], "cash": SEED_ISA_CASH,
            "priceDate": None, "priceUpdatedAt": None,
            "dividends": [], "dividendDate": None},
    "pen": {"holdings": [], "cash": SEED_PEN_CASH,
            "priceDate": None, "priceUpdatedAt": None,
            "dividends": [], "dividendDate": None},
    "irp": {"holdings": [], "cash": SEED_IRP_CASH,
            "priceDate": None, "priceUpdatedAt": None,
            "dividends": [], "dividendDate": None},
    "gen": {"holdings": [], "cash": SEED_GEN_CASH,
            "priceDate": None, "priceUpdatedAt": None,
            "dividends": [], "dividendDate": None},
}


# ---------------------------------------------------------------------------
def _safe_replace(tmp: str, dst: str, attempts: int = 6) -> None:
    """OneDrive 동기화 클라이언트가 파일을 잠그면 os.replace 가 PermissionError 를
    낸다. 잠깐 기다렸다 재시도하고, 끝내 안 되면 내용을 직접 덮어쓴다."""
    for i in range(attempts):
        try:
            os.replace(tmp, dst)
            return
        except PermissionError:
            time.sleep(0.3 * (i + 1))
        except FileNotFoundError:
            return
    log.warning("%s 원자적 교체 실패 - 직접 덮어씁니다 (OneDrive 잠금 추정)",
                os.path.basename(dst))
    try:
        with open(tmp, "rb") as s, open(dst, "wb") as d:
            shutil.copyfileobj(s, d)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _safe_backup(src: str, dst: str) -> None:
    try:
        shutil.copy2(src, dst)
    except (PermissionError, OSError) as e:
        log.debug("백업 생략 (%s)", e)


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# state.json
# ---------------------------------------------------------------------------
def _seed_state(account: str) -> dict:
    """그 계좌의 시드 한 벌을 만든다.

    prevPrice 를 price 와 같은 값으로 시작하는 이유: 전일 종가를 모르는 상태라
    억지로 다른 값을 넣으면 첫 화면의 '전일대비'가 거짓말을 한다. 같게 두면 0 이 된다.
    등록부에만 있고 시드가 없는 계좌(앞으로 더할 IRP 등)는 빈 계좌로 시작한다.
    """
    seed = SEED.get(accounts.require(account), {})
    holdings = [{**h,
                 "prevPrice": h["price"],
                 "priceDate": seed.get("priceDate"),
                 "memo": ""} for h in seed.get("holdings", [])]
    return {
        "version": 1,
        "holdings": holdings,
        "cash": seed.get("cash", 0),
        "strategy": {"text": "", "updatedAt": None},
        "startDate": None,
        "priceUpdatedAt": seed.get("priceUpdatedAt"),
    }


@contextlib.contextmanager
def state_lock():
    """읽기→고치기→쓰기 한 묶음을 감싸는 잠금.

    평일 16:05 스케줄러(시세 갱신·마감 저장)는 사용자 요청과 다른 스레드에서 돈다.
    양쪽이 동시에 load_state() 로 같은 내용을 읽으면, 나중에 save_state() 한 쪽이
    상대의 수정을 통째로 덮어쓴다 — 사용자가 방금 입력한 체결이 조용히 사라지는데
    trades.csv 에는 남아 있어서 원인을 찾기가 아주 어렵다.
    그래서 상태를 바꾸는 쪽은 반드시 이 잠금 안에서 load→save 를 끝낸다.
    RLock 인 이유: 잠금을 쥔 채 다른 잠긴 함수를 부르는 경로(run-now 등)가 있다.
    """
    with _STATE_LOCK:
        yield


def load_state(account: str) -> dict:
    """상태를 읽는다. 없으면 시드로 새로 만들어 저장한 뒤 그것을 돌려준다."""
    path = state_path(account)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    state = _seed_state(account)
    save_state(account, state)
    _seed_dividends(account)   # 배당 시드도 이때 한 번만 깔아 둔다
    log.info("%s: state.json 이 없어 시드 %d종목으로 새로 만들었습니다",
             account, len(state["holdings"]))
    return state


def save_state(account: str, state: dict) -> None:
    path = state_path(account)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):                           # 직전 상태 백업
        _safe_backup(path, path + ".bak")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    _safe_replace(tmp, path)


def new_holding_id() -> str:
    """종목 고유키. code 는 바뀔 수 있고 같은 코드가 두 번 들어갈 수도 있어서
    화면·API 는 이 id 로만 종목을 지목한다.

    밀리초만으로는 한 번에 여러 건을 추가할 때 겹칠 수 있어 2자리 난수를 덧붙인다."""
    return "h%d%02d" % (int(time.time() * 1000), random.randint(0, 99))


# ---------------------------------------------------------------------------
# CSV 공용
# ---------------------------------------------------------------------------
def _read_csv(path: str) -> list:
    if not os.path.exists(path):
        return []
    # 엑셀로 열었다 저장하면 BOM 이 붙으므로 utf-8-sig 로 읽는다.
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _append_csv(path: str, cols: list, row: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if new:
            w.writeheader()
        w.writerow({c: row.get(c, "") for c in cols})


def _write_csv(path: str, cols: list, rows: list) -> None:
    """파일 전체를 한 번에 교체한다 (임시 파일 -> 원자적 교체)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    _safe_replace(tmp, path)


# ---------------------------------------------------------------------------
# history.csv — 일별 마감 스냅샷
# ---------------------------------------------------------------------------
def read_history(account: str) -> list:
    return _read_csv(_p(account, "history.csv"))


def write_history(account: str, rows: list) -> None:
    """이력 전체를 한 번에 교체한다 (정리·복구용)."""
    _write_csv(_p(account, "history.csv"), HISTORY_COLS,
               sorted(rows, key=lambda r: str(r.get("date", ""))))


def upsert_history_row(account: str, row: dict) -> None:
    """같은 날짜가 이미 있으면 덮어쓴다.

    '오늘 마감 저장'을 하루에 몇 번 눌러도 그날 줄이 하나만 남게 하려는 것이다.
    """
    date = str(row.get("date", ""))
    kept = [r for r in read_history(account) if str(r.get("date", "")) != date]
    merged = kept + [{**row, "date": date, "savedAt": row.get("savedAt") or _now()}]
    write_history(account, merged)


# ---------------------------------------------------------------------------
# trades.csv — 체결·변경 이력
# ---------------------------------------------------------------------------
def read_trades(account: str) -> list:
    return _read_csv(_p(account, "trades.csv"))


def append_trade(account: str, row: dict) -> None:
    """종목 시트·관리에서 일어난 변경을 한 줄 남긴다 (action: buy/sell/add/remove/edit/cash/dividend)."""
    _append_csv(_p(account, "trades.csv"), TRADE_COLS,
                {**row, "ts": row.get("ts") or _now()})


# ---------------------------------------------------------------------------
# dividends.csv — 배당 입금
# ---------------------------------------------------------------------------
def read_dividends(account: str) -> list:
    return _read_csv(_p(account, "dividends.csv"))


def append_dividend(account: str, row: dict) -> None:
    _append_csv(_p(account, "dividends.csv"), DIVIDEND_COLS,
                {**row, "ts": row.get("ts") or _now()})


def _seed_dividends(account: str) -> None:
    """그 계좌의 시드 배당. 이미 파일이 있으면 사용자가 쌓은 기록이므로 손대지 않는다."""
    path = _p(account, "dividends.csv")
    if os.path.exists(path):
        return
    seed = SEED.get(accounts.require(account), {})
    rows, day = seed.get("dividends") or [], seed.get("dividendDate")
    if not rows or not day:
        return
    ts = day + "T00:00:00"                      # 실제 입력 시각을 모르므로 지급일 0시로 둔다
    _write_csv(path, DIVIDEND_COLS,
               [{"date": day, "code": d["code"], "name": d["name"],
                 "amount": d["amount"], "ts": ts} for d in rows])
