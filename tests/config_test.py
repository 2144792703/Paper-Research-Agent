"""配置解析与启动校验的离线单测。"""

import config


def test_clamp_int_falls_back_on_invalid():
    assert config._clamp_int("abc", 1, 10, 5) == 5
    assert config._clamp_int(None, 1, 10, 5) == 5


def test_clamp_int_bounds():
    assert config._clamp_int(-3, 1, 10, 5) == 1
    assert config._clamp_int(99, 1, 10, 5) == 10
    assert config._clamp_int("7", 1, 10, 5) == 7


def test_clamp_float_falls_back_on_invalid():
    assert config._clamp_float("abc", 1.0, 10.0, 5.0) == 5.0
    assert config._clamp_float(-1, 1.0, 10.0, 5.0) == 1.0


def test_provider_tag_shape():
    tag = config.PROVIDER_TAG
    if config.MODEL_PROVIDER == "local":
        assert tag == "local"
    else:
        assert tag.startswith("remote:")
        assert len(tag.split(":", 1)[1]) == 8


def test_validate_config_accepts_test_env():
    # conftest 已注入 MODEL/API_KEY；normal remote 配置应通过
    config.validate_config()
