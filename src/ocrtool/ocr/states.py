"""识别状态机（spec: ocr-execution，design D4）。

六态：空闲 / 加载模型 / 识别中 / 成功 / 空结果 / 错误。
「空结果」单列一态——归入成功会让用户无法区分「没识别出来」与
「程序出问题」，归入错误则对正常输入弹窗过度反应。
"""

from __future__ import annotations

from enum import Enum, auto


class OcrState(Enum):
    IDLE = auto()
    LOADING = auto()
    RECOGNIZING = auto()
    SUCCESS = auto()
    EMPTY = auto()
    ERROR = auto()


# design D4 图的每条转换路径；LOADING → ERROR 是图中「错误」汇的自然
# 延伸：引擎加载失败同样必须进入错误态而非卡在加载态。
# LOADING → IDLE 为模型切换专属（model-switching）：切换以加载态开始、
# 以回空闲结束，成功失败皆然（spec: ocr-execution 切换完成后恢复）。
VALID_TRANSITIONS: dict[OcrState, frozenset[OcrState]] = {
    OcrState.IDLE: frozenset({OcrState.LOADING, OcrState.RECOGNIZING}),
    OcrState.LOADING: frozenset({OcrState.RECOGNIZING, OcrState.ERROR, OcrState.IDLE}),
    OcrState.RECOGNIZING: frozenset({OcrState.SUCCESS, OcrState.EMPTY, OcrState.ERROR}),
    OcrState.SUCCESS: frozenset({OcrState.IDLE}),
    OcrState.EMPTY: frozenset({OcrState.IDLE}),
    OcrState.ERROR: frozenset({OcrState.IDLE}),
}


class InvalidStateTransition(RuntimeError):
    """非法状态转换——意味着执行模型出现竞态或逻辑错误。"""


class StateMachine:
    """只允许定义内状态转换的最小状态机。"""

    def __init__(self) -> None:
        self._state = OcrState.IDLE

    @property
    def state(self) -> OcrState:
        return self._state

    def can_transition(self, new_state: OcrState) -> bool:
        return new_state in VALID_TRANSITIONS[self._state]

    def transition(self, new_state: OcrState) -> OcrState:
        if not self.can_transition(new_state):
            raise InvalidStateTransition(
                f"非法状态转换：{self._state.name} → {new_state.name}"
            )
        self._state = new_state
        return self._state
