"""ocr/states.py：状态机合法转换约束（任务 2.5，design D4 全部转换路径）。"""

import pytest

from ocrtool.ocr.states import (
    VALID_TRANSITIONS,
    InvalidStateTransition,
    StateMachine,
)
from ocrtool.ocr.states import (
    OcrState as S,
)


def walk(edges: list[S]) -> None:
    machine = StateMachine()
    for state in edges:
        machine.transition(state)


class TestD4Paths:
    def test_首次识别成功完整路径(self):
        walk([S.LOADING, S.RECOGNIZING, S.SUCCESS, S.IDLE])

    def test_首次识别空结果路径(self):
        walk([S.LOADING, S.RECOGNIZING, S.EMPTY, S.IDLE])

    def test_首次识别失败路径(self):
        walk([S.LOADING, S.RECOGNIZING, S.ERROR, S.IDLE])

    def test_加载失败直接进入错误(self):
        walk([S.LOADING, S.ERROR, S.IDLE])

    def test_模型切换路径_加载后回空闲(self):
        """model-switching：切换以加载态开始，成功或失败都以回空闲结束。"""
        walk([S.LOADING, S.IDLE])

    def test_识别结束后接续切换(self):
        """在途识别完成后排队切换：成功 → 空闲 → 加载 → 空闲。"""
        walk([S.LOADING, S.RECOGNIZING, S.SUCCESS, S.IDLE, S.LOADING, S.IDLE])

    def test_模型已加载时跳过加载态(self):
        walk([S.RECOGNIZING, S.SUCCESS, S.IDLE])

    def test_已加载空结果路径(self):
        walk([S.RECOGNIZING, S.EMPTY, S.IDLE])

    def test_已加载失败路径(self):
        walk([S.RECOGNIZING, S.ERROR, S.IDLE])

    def test_初始状态为空闲(self):
        assert StateMachine().state is S.IDLE


class TestForbidden:
    def test_识别中不得再次进入识别中(self):
        machine = StateMachine()
        machine.transition(S.RECOGNIZING)
        with pytest.raises(InvalidStateTransition):
            machine.transition(S.RECOGNIZING)

    @pytest.mark.parametrize(
        "path,bad",
        [
            ([], S.SUCCESS),  # 空闲 → 成功
            ([], S.EMPTY),  # 空闲 → 空结果
            ([], S.ERROR),  # 空闲 → 错误
            ([S.LOADING], S.SUCCESS),  # 加载 → 成功
            ([S.LOADING], S.LOADING),  # 加载 → 加载
            # 注：加载 → 空闲 已因模型切换成为合法路径（上方切换用例）
            ([S.RECOGNIZING], S.IDLE),  # 识别中 → 空闲
            ([S.RECOGNIZING], S.LOADING),  # 识别中 → 加载
            ([S.LOADING, S.RECOGNIZING, S.SUCCESS], S.RECOGNIZING),  # 成功 → 识别中（须先回空闲）
            ([S.LOADING, S.RECOGNIZING, S.EMPTY], S.LOADING),
            ([S.LOADING, S.RECOGNIZING, S.ERROR], S.SUCCESS),
        ],
    )
    def test_非法转换被拒绝(self, path, bad):
        machine = StateMachine()
        for state in path:
            machine.transition(state)
        assert not machine.can_transition(bad)
        with pytest.raises(InvalidStateTransition):
            machine.transition(bad)

    def test_每个状态都有出边定义(self):
        for state in VALID_TRANSITIONS:
            assert isinstance(VALID_TRANSITIONS[state], frozenset)
