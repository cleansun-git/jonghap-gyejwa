# -*- coding: utf-8 -*-
"""계좌 등록부 — 탭 하나 = 계좌 하나.

IRP·연금저축을 더할 때 손대는 곳은 여기 ACCOUNTS 와 store.SEED 두 군데뿐이다.
화면(탭 버튼)·API(?account=)·데이터 폴더(data/<key>/)가 전부 이 목록에서 나온다.

key 는 파일 경로(data/<key>/)에 그대로 들어간다. 그래서 바깥에서 온 값은 반드시
normalize() 를 거쳐야 한다 — 목록에 없는 값은 None 이 되고, 경로에 닿지 않는다.
(".." 같은 값이 폴더를 거슬러 올라가는 일을 막는 유일한 장치다)
"""
from __future__ import annotations

# 이 배포형은 모든 계좌가 "autoPrice": False 다 — KIS 시세 자동 갱신을 쓰지 않는다.
# 받는 사람에게 KIS 키가 없는 것이 정상이고, 키 없이 자동갱신을 시도하면 매일 실패
# 알림만 울린다. 그래서 아예 시도하지 않게 하고, 현재가는 화면에서 직접 넣는다.
# 이 값이 False 면 종목코드 규칙도 KIS 6자리가 아니라 영숫자 1~20자가 된다.
#
# 자기 KIS 키를 넣고 자동갱신을 쓰려면 이 다섯 줄의 autoPrice 를 True 로 바꾸면 된다
# (국내 6자리 종목코드만 됨). README 의 '시세 자동 갱신' 항목에 적어 두었다.
ACCOUNTS = [
    {"key": "dc", "label": "퇴직연금", "title": "퇴직연금(DC)", "autoPrice": False},
    {"key": "isa", "label": "ISA", "title": "ISA", "autoPrice": False},
    {"key": "pen", "label": "연금저축", "title": "연금저축", "autoPrice": False},
    {"key": "irp", "label": "IRP", "title": "개인형 IRP", "autoPrice": False},
    {"key": "gen", "label": "일반", "title": "일반 계좌", "autoPrice": False},
]

DEFAULT = "dc"

KEYS = tuple(a["key"] for a in ACCOUNTS)


def normalize(key) -> str | None:
    """바깥에서 온 계좌값을 등록부의 key 로 바꾼다. 모르는 값이면 None."""
    k = str(key or "").strip().lower()
    return k if k in KEYS else None


def require(key) -> str:
    """normalize 와 같되, 모르는 값이면 ValueError. 저장소 쪽에서 쓴다."""
    k = normalize(key)
    if k is None:
        raise ValueError(f"알 수 없는 계좌입니다: {key!r}")
    return k


def auto_price(key) -> bool:
    """이 계좌의 시세를 KIS 로 자동 갱신할 수 있는가. 모르는 계좌면 False."""
    k = normalize(key)
    a = next((x for x in ACCOUNTS if x["key"] == k), None)
    return bool(a) and a.get("autoPrice", True)


def label(key) -> str:
    k = normalize(key)
    return next((a["label"] for a in ACCOUNTS if a["key"] == k), str(key))


def title(key) -> str:
    k = normalize(key)
    return next((a["title"] for a in ACCOUNTS if a["key"] == k), str(key))
