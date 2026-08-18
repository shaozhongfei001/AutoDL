import re
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
# 允许出现在技能 SKILL.md 前（YAML frontmatter）中的键白名单，与 Codex 技能规范保持一致。
ALLOWED_FRONTMATTER_KEYS = {"name", "description", "license", "allowed-tools", "metadata"}


class SkillValidationTests(unittest.TestCase):
    """对仓库内 skills/ 目录下所有技能元信息做一致性校验。"""

    def test_all_repo_skills_use_codex_compatible_frontmatter(self):
        # 遍历每个技能子目录，逐一检查 SKILL.md 是否存在、frontmatter 是否合法且键是否在白名单内。
        failures = []
        skills_dir = REPO_ROOT / "skills"

        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                failures.append(f"{skill_dir.name}: missing SKILL.md")
                continue

            text = skill_md.read_text()
            match = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
            if not match:
                failures.append(f"{skill_dir.name}: invalid or missing YAML frontmatter")
                continue

            frontmatter = yaml.safe_load(match.group(1)) or {}
            if not isinstance(frontmatter, dict):
                failures.append(f"{skill_dir.name}: frontmatter is not a YAML dictionary")
                continue

            unexpected = sorted(set(frontmatter.keys()) - ALLOWED_FRONTMATTER_KEYS)
            if unexpected:
                failures.append(
                    f"{skill_dir.name}: unexpected keys {', '.join(unexpected)}"
                )

        self.assertEqual(
            failures,
            [],
            msg="Repo skills must keep Codex-compatible frontmatter:\n" + "\n".join(failures),
        )


if __name__ == "__main__":
    unittest.main()
