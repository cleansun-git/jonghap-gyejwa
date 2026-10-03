# -*- coding: utf-8 -*-
"""설정 로딩 (config.yaml + secrets.json + data/overrides.json).

  config.yaml           계좌·알림·런타임 설정 (사람이 읽고 고치는 파일)
  secrets.json          비밀번호·KIS 키·VAPID 키 (git 에 올리지 않는다)
  data/overrides.json   앱에서 바꾼 설정 (config.yaml 보다 우선한다)
"""
from __future__ import annotations

import json
import os

import yaml

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = ROOT_DIR                       # 일부 코드가 ROOT 로 부르므로 별칭을 둔다
CONFIG_PATH = os.path.join(ROOT_DIR, "config.yaml")
SECRETS_PATH = os.path.join(ROOT_DIR, "secrets.json")
# 기본은 프로젝트 안의 data/ 다. PEN_DATA_DIR 로 다른 곳을 가리킬 수 있게 열어둔 이유:
# 검증·시험을 돌릴 때 실제 보유 데이터를 건드리면 안 되기 때문이다.
# (여러 시험을 동시에 돌려도 서로의 state.json 을 덮어쓰지 않는다)
DATA_DIR = os.environ.get("PEN_DATA_DIR", "").strip() or os.path.join(ROOT_DIR, "data")

# 앱에서 바꾼 설정을 영구 저장하는 곳.
#
# 클라우드(도커)에서는 config.yaml 이 '이미지 안'에 있어서 컨테이너를 다시 만들면
# 원래 내용으로 되돌아간다. 영구 볼륨으로 살아남는 건 data/ 뿐이므로,
# 실행 중에 바뀌는 값은 여기에도 같이 적어두고 읽을 때 이쪽을 우선한다.
OVERRIDE_PATH = os.path.join(DATA_DIR, "overrides.json")

# 덮어쓰기를 허용하는 구역. 손상되거나 남이 만든 overrides.json 이
# 엉뚱한 키를 밀어 넣지 못하게 화이트리스트로 막는다.
OVERRIDE_SECTIONS = ("account", "notify", "runtime", "dashboard")


class Settings:
    """config.yaml 한 벌을 읽기 쉬운 속성으로 펼쳐놓은 것.

    이 앱은 전략 엔진이 없어서 설정이 얼마 안 된다. 계좌 표시값·알림 시각·
    시세 출처·성과 탭 기간이 전부다.
    """

    def __init__(self, raw: dict, secrets: dict):
        self.secrets = secrets
        self._parse(raw)

    def _parse(self, raw: dict) -> None:
        # 덮어쓰기 저장 후에도 다시 부르므로 파싱은 따로 떼어 둔다.
        self.raw = raw

        ac = raw.get("account", {})
        self.account_code = str(ac.get("code", "ALL"))
        self.account_name = str(ac.get("name", "종합계좌"))
        self.account_tax = str(ac.get("tax", "계좌별 상이"))

        nt = raw.get("notify", {})
        self.push_enabled = bool(nt.get("push_enabled", True))
        self.daily_hour = int(nt.get("daily_hour", 16))
        # 기본 5분인 이유는 config.yaml 의 daily_minute 주석 참고 (토큰 발급이 겹치지 않게).
        # 손으로 고치다 60 같은 값을 넣어도 스케줄러가 죽지 않도록 0~59 로 가둔다.
        self.daily_minute = min(59, max(0, int(nt.get("daily_minute", 5))))

        rt = raw.get("runtime", {})
        self.timezone = str(rt.get("timezone", "Asia/Seoul"))
        self.price_source = str(rt.get("price_source", "kis"))
        self.log_level = str(rt.get("log_level", "INFO"))

        db = raw.get("dashboard", {})
        self.history_days = int(db.get("history_days", 180))

    # -- secrets -----------------------------------------------------------
    # 클라우드 배포에서는 secrets.json 을 이미지에 넣지 않으므로
    # 환경변수를 먼저 보고, 없으면 secrets.json 을 쓴다.
    def _secret(self, env: str, key: str) -> str:
        return (os.environ.get(env, "").strip()
                or str(self.secrets.get(key, "")).strip())

    @property
    def web_password(self) -> str:
        pw = self._secret("PEN_PASSWORD", "web_password")
        # secrets.example.json 을 그대로 복사하면 "여기에-웹앱-로그인-비밀번호" 가 남는다.
        # 이걸 진짜 비밀번호로 받으면, 이 PC 에선 주인이 못 들어오고 같은 WiFi 에선
        # 누구나 아는 문자열로 문이 열린다. 자리표시자는 '설정 안 함' 으로 본다.
        if pw.startswith("여기에"):
            return ""
        return pw

    @property
    def kis_app_key(self) -> str:
        return self._secret("PEN_KIS_APP_KEY", "kis_app_key")

    @property
    def kis_app_secret(self) -> str:
        return self._secret("PEN_KIS_APP_SECRET", "kis_app_secret")

    @property
    def kis_paper(self) -> bool:
        """모의투자 키인가. JSON 에 문자열 "false" 를 적어도 참이 되지 않게 글자로 판단한다.
        (bool("false") 는 True 라서, 그대로 두면 실전 키로 모의투자 서버에 붙는다)"""
        raw = os.environ.get("PEN_KIS_PAPER", "").strip() or self.secrets.get("kis_paper_trading", False)
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")

    @property
    def kis_ready(self) -> bool:
        """KIS 키가 갖춰졌는가.

        키가 없어도 앱 전체는 정상 동작해야 한다(현재가를 손으로 넣으면 되므로).
        시세 모듈은 예외를 던지지 말고 이 값을 보고 조용히 실패해야 한다.
        """
        return bool(self.kis_app_key and self.kis_app_secret)

    # VAPID 키는 비워 두면 web/push.py 가 data/vapid.json 에 새로 만들어 쓴다.
    # 재배포해도 기존 구독이 살아 있게 하려면 그 키를 여기에 옮겨 적으면 된다.
    @property
    def vapid_public(self) -> str:
        return self._secret("PEN_VAPID_PUBLIC", "vapid_public")

    @property
    def vapid_private(self) -> str:
        return self._secret("PEN_VAPID_PRIVATE", "vapid_private")

    # -- 설정 변경 ---------------------------------------------------------
    def save(self, section: str, key: str, value) -> None:
        """설정 한 항목을 data/overrides.json 에 적고 즉시 반영한다.

        config.yaml 은 건드리지 않는다. 주석이 설명서 역할을 하는 파일이라
        기계가 다시 쓰면 주석이 깨지기 때문이다.
        """
        save_override(section, key, value)
        raw = dict(self.raw)
        sec = dict(raw.get(section) or {})
        sec[key] = value
        raw[section] = sec
        self._parse(raw)


# ---------------------------------------------------------------------------
# 영구 저장용 덮어쓰기 값 (data/overrides.json)
# ---------------------------------------------------------------------------
def load_overrides() -> dict:
    """{"notify": {"daily_hour": 17, "daily_minute": 5}, ...} 모양. 깨져 있으면 조용히 무시한다."""
    if not os.path.exists(OVERRIDE_PATH):
        return {}
    try:
        with open(OVERRIDE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items()
            if k in OVERRIDE_SECTIONS and isinstance(v, dict)}


def save_override(section: str, key: str, value) -> None:
    if section not in OVERRIDE_SECTIONS:
        return
    data = load_overrides()
    data.setdefault(section, {})[key] = value
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = OVERRIDE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OVERRIDE_PATH)


def clear_overrides() -> None:
    """config.yaml 을 손으로 고쳤는데 반영이 안 될 때 쓰는 비상 탈출구."""
    if os.path.exists(OVERRIDE_PATH):
        os.remove(OVERRIDE_PATH)


def load() -> Settings:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f.read()) or {}
    os.makedirs(DATA_DIR, exist_ok=True)

    # 실행 중에 바뀐 설정이 있으면 config.yaml 보다 우선한다.
    # 구역 단위가 아니라 항목 단위로 덮어써야 config.yaml 에만 있는 값이 지워지지 않는다.
    for section, vals in load_overrides().items():
        merged = dict(raw.get(section) or {})
        merged.update(vals)
        raw[section] = merged

    secrets = {}
    if os.path.exists(SECRETS_PATH):
        # 메모장으로 저장한 secrets.json 은 BOM 이 붙어 json 파서가 죽는다 -> utf-8-sig
        with open(SECRETS_PATH, "r", encoding="utf-8-sig") as f:
            secrets = json.load(f)
    return Settings(raw, secrets)
