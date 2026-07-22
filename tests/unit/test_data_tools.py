"""I4 数据工具测试 - 迁移 + 备份/导入。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.export import export_data, import_data
from scripts.migrate import migrate_from_astrbot, migrate_from_maibot


class TestAstrBotMigration:
    @pytest.mark.asyncio
    async def test_migrate_with_llm_config(self, tmp_path: Path) -> None:
        src = tmp_path / "astrbot"
        src.mkdir()
        # 构造 AstrBot 配置
        (src / "cmd_config.json").write_text(
            json.dumps({
                "provider_llm": {
                    "type": "openai_chat",
                    "key": "sk-test",
                    "model": "gpt-4",
                    "api_base": "https://api.openai.com/v1",
                }
            }),
            encoding="utf-8",
        )

        dst = tmp_path / "isac_data"
        report = migrate_from_astrbot(src, dst, dry_run=False)

        assert report["ok"] is True
        assert (dst / "config.jsonc").exists()
        config = json.loads((dst / "config.jsonc").read_text(encoding="utf-8"))
        assert config["llm"]["provider"] == "openai_compat"
        assert config["llm"]["api_key"] == "sk-test"
        assert config["llm"]["model"] == "gpt-4"

    @pytest.mark.asyncio
    async def test_migrate_dry_run_does_not_write(self, tmp_path: Path) -> None:
        src = tmp_path / "astrbot"
        src.mkdir()
        dst = tmp_path / "isac_data"
        report = migrate_from_astrbot(src, dst, dry_run=True)

        assert report["dry_run"] is True
        assert not (dst / "config.jsonc").exists()

    @pytest.mark.asyncio
    async def test_migrate_copies_plugins(self, tmp_path: Path) -> None:
        src = tmp_path / "astrbot"
        (src / "data" / "plugin" / "my_plugin").mkdir(parents=True)
        (src / "data" / "plugin" / "my_plugin" / "__init__.py").write_text("", encoding="utf-8")
        dst = tmp_path / "isac_data"

        migrate_from_astrbot(src, dst, dry_run=False)

        # plugins 目录应被复制 (dst 父目录下, 因 dst 名为 isac_data)
        plugins_dir = tmp_path / "plugins"
        assert plugins_dir.exists()
        assert (plugins_dir / "my_plugin" / "__init__.py").exists()


class TestMaiBotMigration:
    @pytest.mark.asyncio
    async def test_migrate_creates_default_agent(self, tmp_path: Path) -> None:
        src = tmp_path / "maibot"
        src.mkdir()
        # 构造 MaiBot 配置 (TOML)
        (src / "config.toml").write_text(
            '[LLM]\napi_key = "sk-mai"\nmodel = "gpt-3.5-turbo"\nbase_url = "https://api.openai.com/v1"\n'
            '[bot]\nnickname = "MaiBot"\nbot_qq = "10001"\nalias_names = ["小麦"]\n',
            encoding="utf-8",
        )
        dst = tmp_path / "isac_data"

        report = migrate_from_maibot(src, dst, dry_run=False)

        assert report["ok"] is True
        agent_config_path = dst / "agents" / "default" / "config.jsonc"
        assert agent_config_path.exists()
        agent_config = json.loads(agent_config_path.read_text(encoding="utf-8"))
        assert agent_config["agent_id"] == "default"
        assert agent_config["display_name"] == "MaiBot"
        assert "小麦" in agent_config["trigger_words"]

        config = json.loads((dst / "config.jsonc").read_text(encoding="utf-8"))
        assert config["bot_id"] == "10001"
        assert config["llm"]["api_key"] == "sk-mai"

    @pytest.mark.asyncio
    async def test_migrate_without_config_toml(self, tmp_path: Path) -> None:
        src = tmp_path / "maibot"
        src.mkdir()
        dst = tmp_path / "isac_data"

        report = migrate_from_maibot(src, dst, dry_run=False)

        # 即使 config.toml 缺失, 仍能生成 stub 配置
        assert report["ok"] is True
        config = json.loads((dst / "config.jsonc").read_text(encoding="utf-8"))
        assert config["llm"]["provider"] == "stub"


class TestExportImport:
    def test_export_creates_zip(self, tmp_path: Path) -> None:
        src = tmp_path / "data"
        src.mkdir()
        (src / "config.jsonc").write_text("{}", encoding="utf-8")
        (src / "audit.ndjson").write_text("line1\n", encoding="utf-8")  # 默认排除
        out = tmp_path / "backup.zip"

        report = export_data(src, out, include_logs=False)

        assert report["ok"] is True
        assert report["files"] == 1  # 仅 config.jsonc, 排除 audit.ndjson
        assert out.exists()
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            assert "config.jsonc" in names
            assert "audit.ndjson" not in names

    def test_export_includes_logs_when_requested(self, tmp_path: Path) -> None:
        src = tmp_path / "data"
        src.mkdir()
        (src / "config.jsonc").write_text("{}", encoding="utf-8")
        (src / "audit.ndjson").write_text("line1\n", encoding="utf-8")
        out = tmp_path / "backup.zip"

        report = export_data(src, out, include_logs=True)

        assert report["files"] == 2
        with zipfile.ZipFile(out) as zf:
            assert "audit.ndjson" in zf.namelist()

    def test_import_restores_files(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "backup.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("config.jsonc", '{"test": true}')
            zf.writestr("agents/default/config.jsonc", '{"agent_id": "default"}')

        dst = tmp_path / "restored"

        report = import_data(zip_path, dst, overwrite=False)

        assert report["ok"] is True
        assert report["files"] == 2
        assert (dst / "config.jsonc").exists()
        assert (dst / "agents" / "default" / "config.jsonc").exists()
        assert json.loads((dst / "config.jsonc").read_text(encoding="utf-8"))["test"] is True

    def test_import_skips_existing_without_overwrite(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "backup.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("config.jsonc", '{"new": true}')

        dst = tmp_path / "restored"
        dst.mkdir()
        (dst / "config.jsonc").write_text('{"existing": true}', encoding="utf-8")

        report = import_data(zip_path, dst, overwrite=False)

        assert report["skipped"] == 1
        assert json.loads((dst / "config.jsonc").read_text(encoding="utf-8"))["existing"] is True

    def test_import_overwrites_when_flag_set(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "backup.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("config.jsonc", '{"new": true}')

        dst = tmp_path / "restored"
        dst.mkdir()
        (dst / "config.jsonc").write_text('{"existing": true}', encoding="utf-8")

        report = import_data(zip_path, dst, overwrite=True)

        assert report["files"] == 1
        assert json.loads((dst / "config.jsonc").read_text(encoding="utf-8"))["new"] is True

    def test_export_excludes_venv_and_pycache(self, tmp_path: Path) -> None:
        src = tmp_path / "data"
        (src / ".venv" / "lib").mkdir(parents=True)
        (src / ".venv" / "lib" / "x.py").write_text("", encoding="utf-8")
        (src / "__pycache__").mkdir()
        (src / "__pycache__" / "x.pyc").write_text("", encoding="utf-8")
        (src / "config.jsonc").write_text("{}", encoding="utf-8")
        out = tmp_path / "backup.zip"

        report = export_data(src, out)

        assert report["files"] == 1
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            assert ".venv/lib/x.py" not in names
            assert "__pycache__/x.pyc" not in names
