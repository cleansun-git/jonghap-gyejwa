# -*- coding: utf-8 -*-
"""문서 §7 '동작하는가' — 종목 추가·매수·매도·수정·삭제, 현재가 직접 입력,
마감 저장, 성과 전체 합계. 전부 service 계층에서 돌린다 (app.py 는 라우팅만 한다).
"""
import os
import shutil
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="pen_test_crud_")
os.environ["PEN_DATA_DIR"] = TMP
os.environ["PEN_NO_SCHEDULER"] = "1"
for k in ("PEN_KIS_APP_KEY", "PEN_KIS_APP_SECRET"):
    os.environ.pop(k, None)

# tests/ 한 단계 위가 리포 루트다. 어디서 실행하든(루트에서든 tests/ 안에서든)
# 같은 곳을 가리키므로, 실행 위치에 따라 엉뚱한 소스를 불러오는 일이 없다.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, REPO)

import accounts            # noqa: E402
import store               # noqa: E402
from web import service    # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        fails.append(name)


print("[1] 첫 스냅샷 — 5개 계좌가 다 열린다")
for k in accounts.KEYS:
    snap = service.snapshot(k)
    check("%s 스냅샷" % k, isinstance(snap, dict) and "totals" in snap)
    check("%s 그룹 3개(월중/월말/기타)" % k, len(snap["groups"]) == 3,
          [g["key"] for g in snap["groups"]])

dc = service.snapshot("dc")
t = dc["totals"]
check("dc 총금액 10,013,490", t["total"] == 10_013_490, t["total"])
check("dc 평가손익 +21,930", t["evalPl"] == 21_930, t["evalPl"])
check("dc 수익률 +0.24%", round(t["retPct"] * 100, 2) == 0.24, t["retPct"])
check("dc 이번달 배당 18,000", t["thisMonthDividend"] in (0, 18_000), t["thisMonthDividend"])

print("\n[2] 모든 종목 평가금액이 약 100만원, 손익 색이 둘 다 나온다")
items = [i for g in dc["groups"] for i in g["items"]]
check("종목 9개", len(items) == 9, len(items))
for i in items:
    check("%s 평가 %s" % (i["code"], format(i["evalAmount"], ",")),
          950_000 <= i["evalAmount"] <= 1_050_000, i["evalAmount"])
plus = [i for i in items if i["pl"] > 0]
minus = [i for i in items if i["pl"] < 0]
check("수익(빨강) 종목 5개", len(plus) == 5, len(plus))
check("손실(파랑) 종목 4개", len(minus) == 4, len(minus))

print("\n[3] 그룹 소계 검산")
want = {"월중": (2_963_240, 2_990_490, 3), "월말": (5_038_720, 5_003_640, 5),
        "기타": (989_600, 1_019_360, 1)}
for g in dc["groups"]:
    sub = g["subtotal"]
    b, e, c = want[g["key"]]
    check("%s 매수 %s" % (g["key"], format(b, ",")), sub.get("buyAmount") == b, sub.get("buyAmount"))
    check("%s 평가 %s" % (g["key"], format(e, ",")), sub.get("evalAmount") == e, sub.get("evalAmount"))
    check("%s 종목수 %d" % (g["key"], c), sub.get("count") == c, sub.get("count"))

print("\n[4] 종목 추가 — autoPrice=False 라 6자리가 아닌 코드도 받는다")
r = service.save_holding("gen", {
    "id": None, "code": "TESTCODE01", "name": "테스트 종목", "asset": "국내주식",
    "pay": "월중", "qty": 10, "buyPrice": 1000, "price": 1100, "action": "edit"})
check("추가 성공", r.get("ok") is not False, r)
gen = store.load_state("gen")
check("gen 보유 1종목", len(gen["holdings"]) == 1, len(gen["holdings"]))
new = gen["holdings"][0]
check("코드가 그대로 저장(영숫자 1~20자 규칙)", new["code"] == "TESTCODE01", new["code"])
hid = new["id"]
check("id 가 붙었다", bool(hid))

print("\n[5] 매수 — 가중평균 단가 재계산")
# 10주 @1000 보유 -> 10주 @2000 매수 => 20주 @1500
service.save_holding("gen", {"id": hid, "code": "TESTCODE01", "name": "테스트 종목",
                             "asset": "국내주식", "pay": "월중", "price": 1100,
                             "action": "buy", "deltaQty": 10, "deltaPrice": 2000})
h = store.load_state("gen")["holdings"][0]
check("수량 20주", h["qty"] == 20, h["qty"])
check("평균단가 1500", h["buyPrice"] == 1500, h["buyPrice"])

print("\n[6] 매도 — 평균단가는 그대로")
service.save_holding("gen", {"id": hid, "code": "TESTCODE01", "name": "테스트 종목",
                             "asset": "국내주식", "pay": "월중", "price": 1100,
                             "action": "sell", "deltaQty": 5, "deltaPrice": 1800})
h = store.load_state("gen")["holdings"][0]
check("수량 15주", h["qty"] == 15, h["qty"])
check("평균단가 1500 유지", h["buyPrice"] == 1500, h["buyPrice"])

print("\n[7] 수정(edit)")
service.save_holding("gen", {"id": hid, "code": "TESTCODE01", "name": "이름 바꿈",
                             "asset": "선진국주식", "pay": "월말", "qty": 15,
                             "buyPrice": 1500, "price": 1200, "action": "edit"})
h = store.load_state("gen")["holdings"][0]
check("이름 변경", h["name"] == "이름 바꿈", h["name"])
check("자산군 변경", h["asset"] == "선진국주식", h["asset"])
check("배당시기 변경", h["pay"] == "월말", h["pay"])
check("현재가 변경", h["price"] == 1200, h["price"])

print("\n[8] 현재가 직접 입력 (set_prices) — 키는 종목 id 다")
dcst = store.load_state("dc")
id0 = dcst["holdings"][0]["id"]
r = service.set_prices("dc", {id0: 12500})
check("set_prices ok", r.get("ok") is not False, r)
check("1종목 반영", r.get("updated") == 1, r)
after = store.load_state("dc")["holdings"][0]
check("현재가 반영", after["price"] == 12500, after["price"])
check("prevPrice 가 직전 값을 기억한다", after["prevPrice"] == 12280, after["prevPrice"])
# 0·빈칸은 건너뛴다 (안 적은 종목이 0원이 되면 총금액이 무너진다)
id1 = dcst["holdings"][1]["id"]
before1 = store.load_state("dc")["holdings"][1]["price"]
r0 = service.set_prices("dc", {id1: 0, "없는id": 9999})
check("0 과 모르는 id 는 건너뛴다", r0.get("updated") == 0, r0)
check("건너뛴 종목 현재가 그대로", store.load_state("dc")["holdings"][1]["price"] == before1)

print("\n[9] 현금 수정 · 배당 입력")
service.set_cash("gen", 2_500_000)
check("현금 반영", store.load_state("gen")["cash"] == 2_500_000)
service.add_dividend("gen", "TESTCODE01", "이름 바꿈", 5000)
divs = store.read_dividends("gen")
check("배당 1건", len(divs) == 1, len(divs))
check("배당 금액 5000", int(divs[0]["amount"]) == 5000, divs[0])

print("\n[10] 삭제 — 수량 0 이어도 기록은 남는다")
r = service.delete_holding("gen", hid)
check("삭제 ok", r.get("ok") is not False, r)
check("보유 목록에서 빠졌다", store.load_state("gen")["holdings"] == [],
      store.load_state("gen")["holdings"])
trades = store.read_trades("gen")
check("거래 이력이 남아 있다", len(trades) >= 4, len(trades))
acts = [tr["action"] for tr in trades]
print("       이력:", acts)

print("\n[11] 마감 저장 — KIS 키 없이 오류 없이")
for k in accounts.KEYS:
    try:
        c = service.close_today(k)
        check("%s 마감 저장" % k, c.get("ok") is not False, c)
    except ValueError as e:
        # 보유 0 + 현금 0 인 계좌는 ValueError 를 낼 수 있다. gen 은 현금이 있으니 통과해야 한다
        check("%s 마감 저장 (%s)" % (k, e), False, e)

print("\n[12] 시세 갱신 버튼 — KIS 키 없이 오류 없이 끝난다")
for k in accounts.KEYS:
    r = service.refresh_prices(k)
    check("%s refresh ok" % k, r.get("ok") is True, r)

print("\n[13] 성과 — 계좌별 + 전체 합계")
for k in accounts.KEYS:
    h = service.history(k, days=180)
    check("%s history 응답" % k, isinstance(h, dict), type(h))
    rows = h.get("rows") or h.get("history") or []
    check("%s 기록 1줄 이상" % k, len(rows) >= 1, len(rows))
tot = 0
for k in accounts.KEYS:
    tot += service.snapshot(k)["totals"]["total"]
print("       전 계좌 합계: %s 원" % format(tot, ","))
check("전 계좌 합계 > 0", tot > 0, tot)

shutil.rmtree(TMP, ignore_errors=True)
print("\n" + ("=" * 58))
if fails:
    print("실패 %d건:" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_crud.py 전부 통과")
