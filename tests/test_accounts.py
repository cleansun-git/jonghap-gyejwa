# -*- coding: utf-8 -*-
"""계좌 격리 + 경로 탈출 방어 + 배포형 시드 검증.

반드시 PEN_DATA_DIR 을 임시 폴더로 두고 돌린다. 실제 data/ 를 건드리면 안 된다.
KIS 키는 환경변수에서 비워 둔다 — 키가 없어야 네트워크를 전혀 타지 않는다.
"""
import os
import shutil
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="pen_test_acct_")
os.environ["PEN_DATA_DIR"] = TMP
# 실제 KIS 를 건드리지 않게 키를 명시적으로 비운다
for k in ("PEN_KIS_APP_KEY", "PEN_KIS_APP_SECRET", "PEN_VAPID_PUBLIC", "PEN_VAPID_PRIVATE"):
    os.environ.pop(k, None)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) \
    if os.path.basename(os.getcwd()) != "TOTAL_PEN_PUBLIC" else os.getcwd()
# tests/ 한 단계 위가 리포 루트다. 어디서 실행하든(루트에서든 tests/ 안에서든)
# 같은 곳을 가리키므로, 실행 위치에 따라 엉뚱한 소스를 불러오는 일이 없다.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, REPO)

import accounts            # noqa: E402
import settings            # noqa: E402
import store               # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        fails.append(name)


print("데이터 폴더:", settings.DATA_DIR)
check("PEN_DATA_DIR 가 임시 폴더를 가리킨다", settings.DATA_DIR == TMP, settings.DATA_DIR)
check("KIS 키가 없다 (네트워크 안 탐)", not settings.load().kis_ready)

print("\n[1] 계좌 등록부")
check("계좌 5개", len(accounts.ACCOUNTS) == 5, len(accounts.ACCOUNTS))
check("key 목록", accounts.KEYS == ("dc", "isa", "pen", "irp", "gen"), accounts.KEYS)
check("전부 autoPrice=False",
      all(accounts.auto_price(k) is False for k in accounts.KEYS),
      {k: accounts.auto_price(k) for k in accounts.KEYS})

print("\n[2] 경로 탈출 방어")
for bad in ("..", "../..", "..\\..", "dc/../isa", "/etc/passwd", "", None, "DC_", "unknown"):
    check("normalize(%r) -> None" % (bad,), accounts.normalize(bad) is None, accounts.normalize(bad))
check("normalize 는 대소문자를 받아준다", accounts.normalize("DC") == "dc")
for bad in ("..", "dc/../isa", "nope"):
    try:
        store.load_state(bad)
        check("load_state(%r) 가 막힌다" % bad, False, "예외가 안 났다")
    except ValueError:
        check("load_state(%r) 가 ValueError" % bad, True)
# 정상 계좌의 폴더는 DATA_DIR 안에 있어야 한다
for k in accounts.KEYS:
    d = os.path.abspath(store.account_dir(k))
    check("%s 폴더가 DATA_DIR 안" % k, d.startswith(os.path.abspath(TMP)), d)

print("\n[3] 시드 — 배포형 샘플")
dc = store.load_state("dc")
check("dc 9종목", len(dc["holdings"]) == 9, len(dc["holdings"]))
check("dc 현금 100만원", dc["cash"] == 1_000_000, dc["cash"])
ev_total = 0
for h in dc["holdings"]:
    ev = h["qty"] * h["price"]
    ev_total += ev
    check("%s 평가금액이 100만원 근처 (%s)" % (h["code"], format(ev, ",")),
          950_000 <= ev <= 1_050_000, ev)
    check("%s qty == round(1M/price)" % h["code"], h["qty"] == round(1_000_000 / h["price"]))
    check("%s prevPrice == price (첫 화면 전일대비 0)" % h["code"], h["prevPrice"] == h["price"])
check("dc 평가 합계 9,013,490", ev_total == 9_013_490, format(ev_total, ","))
buy_total = sum(h["qty"] * h["buyPrice"] for h in dc["holdings"])
check("dc 매수 합계 8,991,560", buy_total == 8_991_560, format(buy_total, ","))
check("총금액 10,013,490", ev_total + dc["cash"] == 10_013_490)

reds = [h for h in dc["holdings"] if h["price"] > h["buyPrice"]]
blues = [h for h in dc["holdings"] if h["price"] < h["buyPrice"]]
check("수익(빨강) 종목이 있다", len(reds) > 0, len(reds))
check("손실(파랑) 종목이 있다", len(blues) > 0, len(blues))
check("빨강 5 / 파랑 4", (len(reds), len(blues)) == (5, 4), (len(reds), len(blues)))

for k in ("isa", "pen", "irp", "gen"):
    st = store.load_state(k)
    check("%s 보유 없음" % k, st["holdings"] == [], st["holdings"])
    check("%s 현금 100만원" % k, st["cash"] == 1_000_000, st["cash"])

print("\n[4] 자산군 라벨 (해외채권 -> 선진국주식 반영)")
by_code = {h["code"]: h for h in dc["holdings"]}
for code in ("0040Y0", "0013R0"):
    check("%s asset == 선진국주식" % code, by_code[code]["asset"] == "선진국주식", by_code[code]["asset"])
check("해외채권 라벨이 남아 있지 않다",
      not any(h["asset"] == "해외채권" for h in dc["holdings"]))

print("\n[5] 계좌 격리 — 한 계좌를 고쳐도 다른 계좌가 안 변한다")
isa_before = store.load_state("isa")["cash"]
dc2 = store.load_state("dc")
dc2["cash"] = 777
store.save_state("dc", dc2)
check("dc 현금이 바뀌었다", store.load_state("dc")["cash"] == 777)
check("isa 현금은 그대로", store.load_state("isa")["cash"] == isa_before)
check("isa 보유도 그대로", store.load_state("isa")["holdings"] == [])
# 파일이 계좌별로 따로 있는지
for k in ("dc", "isa"):
    check("data/%s/state.json 존재" % k, os.path.exists(store.state_path(k)))
check("dc 와 isa state 경로가 다르다", store.state_path("dc") != store.state_path("isa"))

print("\n[6] 시드 배당")
divs = store.read_dividends("dc")
check("dc 배당 2건", len(divs) == 2, len(divs))
check("배당 합계 18,000", sum(int(d["amount"]) for d in divs) == 18_000,
      sum(int(d["amount"]) for d in divs))
check("배당 날짜 2026-10-02", all(d["date"] == "2026-10-02" for d in divs))
check("isa 배당 없음", store.read_dividends("isa") == [])

shutil.rmtree(TMP, ignore_errors=True)
print("\n" + ("=" * 58))
if fails:
    print("실패 %d건:" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_accounts.py 전부 통과")
