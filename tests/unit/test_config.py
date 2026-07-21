"""utils/config 单元测试。"""

from __future__ import annotations

from isac.utils.config import CONFIG_VERSION, ConfigMigrator


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
