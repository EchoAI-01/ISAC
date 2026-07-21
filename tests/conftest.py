"""全局 pytest fixtures (DEVELOP.md 5.4)。"""

from __future__ import annotations

import pytest

from tests.fixtures.messages import make_isac_message


@pytest.fixture
def isac_message():
    """默认测试消息工厂。"""
    return make_isac_message
