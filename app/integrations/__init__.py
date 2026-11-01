"""연동 플러그인 자동 등록.

이 폴더의 파일에서 Integration 을 상속한 클래스를 찾아 REGISTRY 에 넣는다.
새 시스템 = 이 폴더에 파일 하나 추가 (README의 "새 연동 추가하기" 참고).
"""
from __future__ import annotations

import importlib
import logging
import pkgutil

from .base import Integration

log = logging.getLogger("homeops.integrations")
REGISTRY: dict[str, type[Integration]] = {}


def _discover() -> None:
    for m in pkgutil.iter_modules(__path__):
        if m.name.startswith("_") or m.name == "base":
            continue
        try:
            mod = importlib.import_module(f"{__name__}.{m.name}")
        except Exception:  # noqa: BLE001 - 플러그인 하나가 깨져도 앱은 뜨게
            log.exception("연동 플러그인 %s 를 불러오지 못했습니다", m.name)
            continue
        for obj in vars(mod).values():
            if isinstance(obj, type) and issubclass(obj, Integration) and obj is not Integration and obj.type:
                if obj.type in REGISTRY and REGISTRY[obj.type] is not obj:
                    log.warning("연동 type 중복: %s", obj.type)
                REGISTRY[obj.type] = obj


def get(type_: str) -> type[Integration] | None:
    return REGISTRY.get(type_)


def ordered() -> list[type[Integration]]:
    return sorted(REGISTRY.values(), key=lambda c: (c.category != "smarthome", c.order, c.title))


_discover()
