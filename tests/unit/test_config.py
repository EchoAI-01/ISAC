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
