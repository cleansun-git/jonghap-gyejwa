# -*- coding: utf-8 -*-
"""autoPrice=False 계좌의 일별 마감 분기 검증.

원본에는 autoPrice=False 계좌가 없어서 건너뛰던 분기가, 배포형에서는 전부 돌게 된다.
반드시 PEN_DATA_DIR 을 임시 폴더로 두고 돌린다. KIS 키는 비워 네트워크를 타지 않게 한다.
"""
import os
import shutil
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="pen_test_job_")
os.environ["PEN_DATA_DIR"] = TMP
os.environ["PEN_NO_SCHEDULER"] = "1"          # 앱을 불러도 스케줄러가 뜨지 않게
for k in ("PEN_KIS_APP_KEY", "PEN_KIS_APP_SECRET"):
    os.environ.pop(k, None)

# tests/ 한 단계 위가 리포 루트다. 어디서 실행하든(루트에서든 tests/ 안에서든)
# 같은 곳을 가리키므로, 실행 위치에 따라 엉뚱한 소스를 불러오는 일이 없다.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, REPO)

import datetime as dt     # noqa: E402

import accounts           # noqa: E402
import market             # noqa: E402
import settings           # noqa: E402
import store              # noqa: E402
from web import app as appmod     # noqa: E402
from web import service           # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        fails.append(name)


print("데이터 폴더:", settings.DATA_DIR)
check("임시 폴더를 쓴다", settings.DATA_DIR == TMP, settings.DATA_DIR)
check("KIS 키 없음", not settings.load().kis_ready)

print("\n[1] market.load_keys / is_market_open — 키 없이")
check("load_keys() -> None", market.load_keys() is None, market.load_keys())
open_, why = market.is_market_open(dt.date(2026, 10, 1))      # 목요일
check("평일은 개장일로 본다", open_ is True, (open_, why))
check("사유가 '확인 불가'라고 말한다", "확인 불가" in why, why)
open_sat, why_sat = market.is_market_open(dt.date(2026, 10, 3))   # 토요일
check("토요일은 닫는다", open_sat is False, (open_sat, why_sat))
check("일요일도 닫는다", market.is_market_open(dt.date(2026, 10, 4))[0] is False)

print("\n[2] service.refresh_prices — autoPrice=False 면 KIS 를 안 부른다")
# market.refresh_prices 를 부르면 바로 실패로 표시되게 덮어 둔다
called = {"n": 0}
orig_refresh = market.refresh_prices


def boom(state):
    called["n"] += 1
    raise AssertionError("KIS 를 불렀다! autoPrice=False 인데 호출됐다")


market.refresh_prices = boom
try:
    for k in accounts.KEYS:
        r = service.refresh_prices(k)
        check("%s refresh_prices ok=True" % k, r.get("ok") is True, r)
        check("%s updated==0" % k, r.get("updated") == 0, r)
        check("%s 안내 문구" % k, "직접" in r.get("message", ""), r.get("message"))
    check("market.refresh_prices 가 한 번도 안 불렸다", called["n"] == 0, called["n"])
finally:
    market.refresh_prices = orig_refresh

print("\n[3] 현재가 직접 입력 -> 그 값으로 마감이 쌓인다")
st = store.load_state("dc")
st["holdings"][0]["price"] = 13000                      # 손으로 넣은 현재가
store.save_state("dc", st)
check("직접 넣은 현재가가 저장된다", store.load_state("dc")["holdings"][0]["price"] == 13000)

print("\n[4] _run_one_account — 휴장일 검사를 통과시키고 마감까지")
orig_open = market.is_market_open
market.is_market_open = lambda when=None: (True, "테스트")
try:
    for k in accounts.KEYS:
        res = appmod._run_one_account(k, manual=False)
        check("%s 결과를 돌려준다" % k, res is not None, res)
        if res:
            check("%s 시세 실패로 표시되지 않는다" % k, res.get("note") == "", res.get("note"))
            check("%s 라벨" % k, res.get("label") == accounts.label(k), res.get("label"))
finally:
    market.is_market_open = orig_open

print("\n[5] history.csv 가 쌓였는가")
today = dt.datetime.now(market.KST).date().isoformat()
for k in accounts.KEYS:
    rows = store.read_history(k)
    has_today = any(r.get("date") == today for r in rows)
    if k == "dc":
        check("dc history 에 오늘 줄이 있다", has_today, [r.get("date") for r in rows])
        row = [r for r in rows if r.get("date") == today][0]
        check("dc total 이 0 이 아니다", float(row["total"]) > 0, row.get("total"))
        # 직접 넣은 13000 이 반영됐는지 (81주 * 13000 = 1,053,000)
        ev = sum(h["qty"] * h["price"] for h in store.load_state("dc")["holdings"])
        cash = store.load_state("dc")["cash"]
        check("total == 보유평가 + 현금", abs(float(row["total"]) - (ev + cash)) < 1,
              (row["total"], ev + cash))
    else:
        # 보유 0종목 + 현금만 있는 계좌도 마감이 남아야 한다
        check("%s history 에 오늘 줄이 있다" % k, has_today, [r.get("date") for r in rows])

print("\n[6] 마감을 두 번 저장해도 줄이 늘지 않는다 (upsert)")
before = len(store.read_history("dc"))
market.is_market_open = lambda when=None: (True, "테스트")
try:
    appmod._run_one_account("dc", manual=False)
finally:
    market.is_market_open = orig_open
after = len(store.read_history("dc"))
check("줄 수가 같다", before == after, (before, after))

print("\n[7] 수동 실행(manual=True)은 휴장일 검사를 건너뛴다")
market.is_market_open = lambda when=None: (False, "휴장일(테스트)")
try:
    res = appmod._run_one_account("dc", manual=True)
    check("manual=True 면 휴장일에도 돈다", res is not None, res)
    res2 = appmod._run_one_account("dc", manual=False)
    check("manual=False 면 휴장일에 건너뛴다", res2 is None, res2)
finally:
    market.is_market_open = orig_open

print("\n[8] 성과 — 전 계좌 합계가 나온다")
snap = service.snapshot("dc")
check("dc 스냅샷 총금액 > 0", snap["totals"]["total"] > 0, snap["totals"]["total"])
check("started=True (시작일 없이도 바로 쓴다)", snap["started"] is True)

shutil.rmtree(TMP, ignore_errors=True)
print("\n" + ("=" * 58))
if fails:
    print("실패 %d건:" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_dailyjob.py 전부 통과")
