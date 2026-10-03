# -*- coding: utf-8 -*-
"""웹 푸시(VAPID). 구독 정보는 data/push_subs.json 에 저장한다."""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("push")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _data_dir() -> str:
    """저장 위치는 settings.DATA_DIR 을 따른다.

    여기만 경로를 직접 박아두면 PEN_DATA_DIR 로 데이터 폴더를 옮겨도 푸시 구독과
    VAPID 키만 진짜 data/ 에 남는다. 시험을 돌릴 때 실제 구독 목록을 덮어쓰는 사고가
    실제로 났던 자리라, store·market 과 같은 경로 규칙을 쓰도록 맞춘다.
    settings 를 못 읽는 상황(설정 파손)에서도 푸시가 죽지는 않게 기본값으로 물러난다.
    """
    try:
        import settings                                  # noqa: PLC0415
        return settings.DATA_DIR
    except Exception:                                    # noqa: BLE001
        return os.path.join(ROOT, "data")


def _subs_path() -> str:
    return os.path.join(_data_dir(), "push_subs.json")


def _keys_path() -> str:
    return os.path.join(_data_dir(), "vapid.json")


def _keys() -> dict:
    """VAPID 키쌍. 없으면 만들어 저장한다 (한 번만).

    secrets.json 에 vapid_public/vapid_private 를 적어 두었으면 그것을 먼저 쓴다.
    키가 바뀌면 휴대폰에 등록된 구독이 전부 무효가 되므로, 재배포해도 같은 키를
    쓰고 싶은 사람을 위해 남겨둔 통로다.
    """
    try:
        import settings                                  # noqa: PLC0415
        cfg = settings.load()
        if cfg.vapid_public and cfg.vapid_private:
            return {"private": cfg.vapid_private, "public": cfg.vapid_public}
    except Exception:  # noqa: BLE001
        pass                                             # 설정을 못 읽어도 아래로 진행한다

    if os.path.exists(_keys_path()):
        with open(_keys_path(), encoding="utf-8") as f:
            return json.load(f)
    from py_vapid import Vapid01
    import base64
    from cryptography.hazmat.primitives import serialization

    v = Vapid01()
    v.generate_keys()
    priv = v.private_key.private_numbers().private_value.to_bytes(32, "big")
    pub = v.private_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint)
    b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")  # noqa: E731
    k = {"private": b64(priv), "public": b64(pub)}
    os.makedirs(_data_dir(), exist_ok=True)
    with open(_keys_path(), "w", encoding="utf-8") as f:
        json.dump(k, f)
    log.info("VAPID 키를 새로 만들었습니다: %s", _keys_path())
    return k


def public_key() -> str:
    return _keys()["public"]


def _load() -> list:
    if not os.path.exists(_subs_path()):
        return []
    try:
        with open(_subs_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return []


def _save(subs: list) -> None:
    os.makedirs(_data_dir(), exist_ok=True)
    path = _subs_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(subs, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def add_subscription(sub: dict) -> None:
    subs = _load()
    ep = sub.get("endpoint")
    if not ep:
        return
    # 같은 기기에서 다시 구독하면 endpoint 가 같다. 중복으로 쌓아두면
    # 알림이 두 번 오므로 기존 것을 지우고 새로 넣는다.
    subs = [s for s in subs if s.get("endpoint") != ep]
    subs.append(sub)
    _save(subs)
    log.info("푸시 구독 등록 (총 %d대)", len(subs))


def send_all(title: str, body: str, url: str = "/") -> int:
    """등록된 모든 기기에 푸시. 만료된 구독은 정리한다."""
    subs = _load()
    if not subs:
        return 0
    from pywebpush import webpush, WebPushException
    k = _keys()
    payload = json.dumps({"title": title, "body": body, "url": url},
                         ensure_ascii=False)
    claims = {"sub": "mailto:" + os.environ.get("PEN_CONTACT", "noreply@example.com")}
    alive, sent = [], 0
    for s in subs:
        try:
            webpush(subscription_info=s, data=payload,
                    vapid_private_key=k["private"], vapid_claims=dict(claims))
            alive.append(s)
            sent += 1
        except WebPushException as e:  # noqa: PERF203
            code = getattr(e.response, "status_code", None)
            # 404/410 은 브라우저가 구독을 버렸다는 뜻이라 다시 보낼 필요가 없다.
            # 그 외 실패는 일시적일 수 있으니 구독을 남겨둔다.
            if code in (404, 410):
                log.info("만료된 구독 제거")
            else:
                log.warning("푸시 실패(%s): %s", code, e)
                alive.append(s)
        except Exception as e:  # noqa: BLE001
            log.warning("푸시 예외: %s", e)
            alive.append(s)
    if len(alive) != len(subs):
        _save(alive)
    return sent
