"""utils/config 单元测试。"""

from __future__ import annotations

import pytest

from isac.utils.config import CONFIG_VERSION, ConfigMigrator, load_config


class TestConfigMigrator:
    def test_missing_version_migrates_to_latest(self):
        migrator = ConfigMigrator()
        config = {"debug": True}
        result = migrator.migrate(config)
        assert result["config_version"] == CONFIG_VERSION

    def test_already_latest_skips_migration(self):
        migrator = ConfigMigrator()
        config = {"config_version": CONFIG_VERSION, "debug": True}
        result = migrator.migrate(config)
        assert result["config_version"] == CONFIG_VERSION
        assert result["debug"] is True


class TestDockerComposeEnvMapping:
    """docker-compose.yml 设置的环境变量必须被 load_config() 真正映射进配置。"""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch: pytest.MonkeyPatch):
        for key in (
            "ISAC_CONTROL_HOST",
            "ISAC_CONTROL_PORT",
            "ISAC_CONTROL_ENABLED",
            "ISAC_API_TOKEN",
            "ISAC_LLM_PROVIDER",
            "ISAC_LLM_API_KEY",
            "ISAC_LLM_MODEL",
            "ISAC_ONEBOT_ENABLED",
            "ISAC_ONEBOT_HOST",
            "ISAC_ONEBOT_PORT",
        ):
            monkeypatch.delenv(key, raising=False)

    def test_compose_style_env_vars_populate_control_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ISAC_CONTROL_HOST", "0.0.0.0")
        monkeypatch.setenv("ISAC_CONTROL_PORT", "8765")
        monkeypatch.setenv("ISAC_CONTROL_ENABLED", "true")
        monkeypatch.setenv("ISAC_API_TOKEN", "secret-123")

        config = load_config(tmp_path / "missing_config.jsonc")

        assert config["control"]["enabled"] is True
        assert config["control"]["host"] == "0.0.0.0"
        assert config["control"]["port"] == 8765
        assert isinstance(config["control"]["port"], int)
        assert config["control"]["api_token"] == "secret-123"

    def test_onebot_enabled_false_string_is_real_bool(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ISAC_ONEBOT_ENABLED", "false")
        monkeypatch.setenv("ISAC_ONEBOT_HOST", "0.0.0.0")
        monkeypatch.setenv("ISAC_ONEBOT_PORT", "8080")

        config = load_config(tmp_path / "missing_config.jsonc")

        assert config["channels"]["onebot"]["enabled"] is False
        assert config["channels"]["onebot"]["port"] == 8080
        assert isinstance(config["channels"]["onebot"]["port"], int)

    def test_llm_model_env_var_is_mapped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ISAC_LLM_PROVIDER", "openai_compat")
        monkeypatch.setenv("ISAC_LLM_API_KEY", "sk-xxx")
        monkeypatch.setenv("ISAC_LLM_MODEL", "deepseek-chat")

        config = load_config(tmp_path / "missing_config.jsonc")

        assert config["llm"]["provider"] == "openai_compat"
        assert config["llm"]["api_key"] == "sk-xxx"
        assert config["llm"]["model"] == "deepseek-chat"


class TestZeroConfigStartup:
    """T2: 无 data/config.jsonc 也能启动并对话 (对标 AstrBot 默认配置内置)。"""

    @pytest.fixture(autouse=True)
    def _clean_llm_env(self, monkeypatch: pytest.MonkeyPatch):
        for key in (
            "ISAC_CONTROL_ENABLED", "ISAC_CONTROL_HOST", "ISAC_CONTROL_PORT",
            "ISAC_API_TOKEN", "ISAC_LLM_PROVIDER", "ISAC_LLM_API_KEY", "ISAC_LLM_MODEL",
            "ISAC_ONEBOT_ENABLED", "ISAC_ONEBOT_HOST", "ISAC_ONEBOT_PORT",
        ):
            monkeypatch.delenv(key, raising=False)

    def test_missing_config_uses_builtin_defaults(self, tmp_path, monkeypatch):
        """无 config.jsonc → DEFAULT_CONFIG 兜底, webchat 默认开 + control 默认开 + memory 默认关。
        T3: control 开箱可管理 (仅绑 127.0.0.1) + setup_enabled 首登强制设密码; llm 不依赖 env:
        不论 env 是否注入 provider/key, 无有效真实 key 时 (空或占位符) register_llm_provider
        都走 Stub + 引导 (T1)。"""
        # 显式清掉可能被其他测试注入的 env, 不依赖 autouse fixture 跨类隔离。
        for key in (
            "ISAC_CONTROL_ENABLED", "ISAC_CONTROL_HOST", "ISAC_CONTROL_PORT",
            "ISAC_API_TOKEN", "ISAC_LLM_PROVIDER", "ISAC_LLM_API_KEY", "ISAC_LLM_MODEL",
        ):
            monkeypatch.delenv(key, raising=False)
        config = load_config(tmp_path / "missing_config.jsonc")

        # webchat 默认开 (零配置即能 WebChat 聊)
        assert config["channels"]["webchat"]["enabled"] is True
        assert config["channels"]["webchat"]["bind_host"] == "127.0.0.1"
        assert config["channels"]["webchat"]["bind_port"] == 8090
        # control 默认开 + setup_enabled 默认开 (T3: 开箱可管理 + 首登强制设密码;
        # 仅绑 127.0.0.1, admin 端点首登态 428 SETUP_REQUIRED 直到 POST /setup)
        assert config["control"]["enabled"] is True
        assert config["control"]["setup_enabled"] is True
        # memory 默认关 (不引入隐式 SQLite/embedding 启动)
        assert config["memory"]["enabled"] is False
        # llm: 默认 {} 或 env 注入的占位符 key, is_placeholder_key 都判为未配置 → Stub
        from isac.utils.config_schema import is_placeholder_key

        assert is_placeholder_key(config["llm"].get("api_key"))

    def test_user_config_overrides_defaults(self, tmp_path):
        """用户显式提供 config.jsonc 时覆盖默认值 (config.update 浅合并语义)。"""
        (tmp_path / "config.jsonc").write_text(
            '{"channels": {"webchat": {"enabled": false, "bind_port": 9999}}}',
            encoding="utf-8",
        )
        config = load_config(tmp_path / "config.jsonc")

        assert config["channels"]["webchat"]["enabled"] is False
        assert config["channels"]["webchat"]["bind_port"] == 9999


class TestEnsureDataDirs:
    """T2: 首启自动创建 data/ 及被引用子目录。"""

    def test_creates_all_subdirs(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from isac.main import _ensure_data_dirs

        _ensure_data_dirs()

        for sub in ("agents", "memory", "gateway", "artifacts", "subagent", "usage", "workflows"):
            assert (tmp_path / "data" / sub).is_dir(), f"缺失子目录 data/{sub}"

    def test_idempotent_no_error_on_existing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from isac.main import _ensure_data_dirs

        _ensure_data_dirs()
        _ensure_data_dirs()  # 再次调用不应报错
        assert (tmp_path / "data" / "agents").is_dir()
