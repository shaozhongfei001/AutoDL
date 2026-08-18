import tempfile
import unittest
from pathlib import Path

import install


class InstallHelpersTests(unittest.TestCase):
    """install 工具函数与「安装/卸载」流程的单元测试，覆盖 Claude 与 Codex 两套目标目录。"""

    def test_build_codex_skill_text_strips_argument_hint(self):
        # Codex 技能正文不应保留仅供 Claude 使用的 argument-hint 字段，
        # 并把技能调用占位符从 #/name 转为 $name 形式。
        source = """---
name: auto-experiment
description: "Launch experiment loop"
argument-hint: "[--project <path>]"
---

# /auto-experiment

Body text.
"""
        rendered = install._build_codex_skill_text(source)

        self.assertNotIn("argument-hint", rendered)
        self.assertIn("$auto-experiment", rendered)
        self.assertIn("# /auto-experiment", rendered)

    def test_install_and_uninstall_cover_claude_and_codex(self):
        # 在临时目录中模拟一次从 repo 到两套目标（.claude / .codex）的安装，
        # 再验证卸载能完整清除——所有路径都应落在临时目录内。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            claude_dir = root / ".claude"
            codex_dir = root / ".codex"

            (repo / "skills" / "auto-experiment" / "agents").mkdir(parents=True)
            (repo / "core").mkdir(parents=True)
            (repo / "gpu").mkdir(parents=True)

            (repo / "skills" / "auto-experiment" / "SKILL.md").write_text(
                """---
name: auto-experiment
description: "Launch experiment loop"
argument-hint: "[--project <path>]"
---

# /auto-experiment

Body text.
"""
            )
            (repo / "skills" / "auto-experiment" / "agents" / "openai.yaml").write_text(
                'interface:\n  display_name: "Auto Experiment"\n'
            )
            (repo / "core" / "loop.py").write_text("print('core')\n")
            (repo / "gpu" / "detect.py").write_text("print('gpu')\n")
            (repo / "config.yaml").write_text("agent:\n  provider: anthropic\n")

            install.install(claude_dir=claude_dir, codex_dir=codex_dir, repo_dir=repo)

            claude_skill = claude_dir / "commands" / "auto-experiment.md"
            codex_skill = codex_dir / "skills" / "auto-experiment" / "SKILL.md"
            codex_ui_meta = codex_dir / "skills" / "auto-experiment" / "agents" / "openai.yaml"
            codex_runtime = codex_dir / "deep-researcher" / "core" / "loop.py"

            self.assertTrue(claude_skill.exists())
            self.assertIn("argument-hint", claude_skill.read_text())

            self.assertTrue(codex_skill.exists())
            self.assertNotIn("argument-hint", codex_skill.read_text())
            self.assertIn("$auto-experiment", codex_skill.read_text())

            self.assertTrue(codex_ui_meta.exists())
            self.assertTrue(codex_runtime.exists())

            install.uninstall(claude_dir=claude_dir, codex_dir=codex_dir, repo_dir=repo)

            self.assertFalse(claude_skill.exists())
            self.assertFalse((codex_dir / "skills" / "auto-experiment").exists())
            self.assertFalse((codex_dir / "deep-researcher").exists())

    def test_install_refuses_to_overwrite_unowned_codex_skill(self):
        # 若目标 codex 技能已存在且并非由本工具创建，安装必须拒绝覆盖（防误销毁外来文件）。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            claude_dir = root / ".claude"
            codex_dir = root / ".codex"

            (repo / "skills" / "auto-experiment").mkdir(parents=True)
            (repo / "core").mkdir(parents=True)
            (repo / "gpu").mkdir(parents=True)
            (repo / "skills" / "auto-experiment" / "SKILL.md").write_text(
                """---
name: auto-experiment
description: "Launch experiment loop"
---

Body.
"""
            )
            (repo / "config.yaml").write_text("agent:\n  provider: anthropic\n")
            foreign_skill = codex_dir / "skills" / "auto-experiment"
            foreign_skill.mkdir(parents=True)
            (foreign_skill / "SKILL.md").write_text("foreign\n")

            with self.assertRaises(RuntimeError):
                install.install(claude_dir=claude_dir, codex_dir=codex_dir, repo_dir=repo)

            self.assertFalse((claude_dir / "commands" / "auto-experiment.md").exists())


if __name__ == "__main__":
    unittest.main()
