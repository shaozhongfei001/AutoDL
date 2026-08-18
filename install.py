"""
将 Deep Researcher Agent 的集成安装进 Claude Code 与 Codex。

一条命令完成安装：
    python install.py

安装完成后：
    - Claude Code 的斜杠命令会被复制到 ~/.claude/commands
    - Codex 的本地技能会被复制到 ~/.codex/skills
"""

import re
import shutil
import sys
from pathlib import Path

import yaml


# 目标安装目录（用户主目录下的配置文件位置）
CLAUDE_DIR = Path.home() / ".claude"
CODEX_DIR = Path.home() / ".codex"
# 仓库根目录（install.py 所在目录）
REPO_DIR = Path(__file__).parent
# 技能源目录
SKILLS_SOURCE = REPO_DIR / "skills"
CORE_SOURCE = REPO_DIR / "core"
GPU_SOURCE = REPO_DIR / "gpu"
# Codex 技能 frontmatter 仅允许这些字段（其余 Claude 专属字段会被过滤掉）
CODEX_ALLOWED_FRONTMATTER = {"name", "description", "license", "allowed-tools", "metadata"}
# 安装标记文件名（用于判断某 Codex 技能是否由本安装器安装，避免误覆盖）
CODEX_INSTALL_MARKER = ".deep-researcher-installed"


def _iter_skill_dirs(skills_source: Path):
    # 遍历所有含 SKILL.md 的技能目录
    for skill_dir in sorted(skills_source.iterdir()):
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
            yield skill_dir


def _sync_python_modules(source_dir: Path, dest_dir: Path):
    # 把一个目录里的所有 .py 文件复制到目标目录（用于同步 core/gpu 运行时模块）
    dest_dir.mkdir(parents=True, exist_ok=True)
    if source_dir.exists():
        for py_file in source_dir.glob("*.py"):
            shutil.copy2(py_file, dest_dir / py_file.name)


def _install_runtime_bundle(home_dir: Path, repo_dir: Path):
    # 把 core/gpu 运行时模块与 config.yaml 安装到 deep-researcher 包目录
    bundle_dir = home_dir / "deep-researcher"
    _sync_python_modules(repo_dir / "core", bundle_dir / "core")
    _sync_python_modules(repo_dir / "gpu", bundle_dir / "gpu")

    config_src = repo_dir / "config.yaml"
    config_dest = bundle_dir / "config.yaml"
    if config_src.exists() and not config_dest.exists():
        config_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config_src, config_dest)


def _check_codex_conflicts(skills_source: Path, codex_dir: Path):
    # 安装前检查：若目标已存在技能但没有本安装器标记，则拒绝覆盖（避免误删用户自定义技能）
    codex_skills_dir = codex_dir / "skills"
    for skill_dir in _iter_skill_dirs(skills_source):
        dest_dir = codex_skills_dir / skill_dir.name
        if dest_dir.exists():
            marker = dest_dir / CODEX_INSTALL_MARKER
            if not marker.exists():
                raise RuntimeError(
                    f"拒绝覆盖已存在的 Codex 技能 '{skill_dir.name}' "
                    f"（位于 {dest_dir}）；未找到安装标记文件。"
                )


def _parse_frontmatter(skill_text: str):
    # 解析技能文件的 YAML frontmatter（--- 之间）与正文
    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", skill_text, re.DOTALL)
    if not match:
        raise ValueError("技能文件必须以 YAML frontmatter 开头")
    frontmatter = yaml.safe_load(match.group(1)) or {}
    if not isinstance(frontmatter, dict):
        raise ValueError("技能 frontmatter 必须是 YAML 字典")
    body = match.group(2)
    return frontmatter, body


def _build_codex_skill_text(skill_text: str) -> str:
    # 把 Claude 技能文本转换为 Codex 技能文本：过滤 frontmatter 只保留允许的字段，
    # 并加一段 Codex 调用说明。
    frontmatter, body = _parse_frontmatter(skill_text)
    filtered_frontmatter = {
        key: value
        for key, value in frontmatter.items()
        if key in CODEX_ALLOWED_FRONTMATTER
    }
    skill_name = str(filtered_frontmatter.get("name", "")).strip()
    codex_note = (
        f"> Codex 备注：需要时显式调用 `${skill_name}`。原始仓库文档也可能显示 "
        f"`/{skill_name}`，因为同一份源技能同时驱动 Claude Code 的斜杠命令。\n\n"
    )
    rendered_frontmatter = yaml.safe_dump(
        filtered_frontmatter,
        sort_keys=False,
        allow_unicode=True,
    ).strip()
    return f"---\n{rendered_frontmatter}\n---\n\n{codex_note}{body.lstrip()}"


def _install_claude_commands(skills_source: Path, claude_dir: Path) -> int:
    # 把每个技能复制为 Claude Code 的斜杠命令（/技能名）
    claude_commands = claude_dir / "commands"
    claude_commands.mkdir(parents=True, exist_ok=True)

    installed = 0
    for skill_dir in _iter_skill_dirs(skills_source):
        dest = claude_commands / f"{skill_dir.name}.md"
        shutil.copy2(skill_dir / "SKILL.md", dest)
        print(f"    ✓ Claude /{skill_dir.name}")
        installed += 1
    return installed


def _install_codex_skills(skills_source: Path, codex_dir: Path) -> int:
    # 把每个技能安装为 Codex 的本地技能（$技能名），并写入安装标记
    codex_skills_dir = codex_dir / "skills"
    codex_skills_dir.mkdir(parents=True, exist_ok=True)

    installed = 0
    for skill_dir in _iter_skill_dirs(skills_source):
        dest_dir = codex_skills_dir / skill_dir.name
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        shutil.copytree(skill_dir, dest_dir)
        skill_text = (skill_dir / "SKILL.md").read_text()
        (dest_dir / "SKILL.md").write_text(_build_codex_skill_text(skill_text))
        (dest_dir / CODEX_INSTALL_MARKER).write_text("installed by Deep Researcher Agent\n")
        print(f"    ✓ Codex ${skill_dir.name}")
        installed += 1
    return installed


def install(
    claude_dir: Path = CLAUDE_DIR,
    codex_dir: Path = CODEX_DIR,
    repo_dir: Path = REPO_DIR,
):
    # 主安装流程：检查冲突 → 安装 Claude 命令 → 安装 Codex 技能 → 安装运行时模块
    print()
    print("  Deep Researcher Agent — 安装程序")
    print("  " + "=" * 40)
    print()

    skills_source = repo_dir / "skills"
    _check_codex_conflicts(skills_source, codex_dir)
    claude_count = _install_claude_commands(skills_source, claude_dir)
    codex_count = _install_codex_skills(skills_source, codex_dir)
    _install_runtime_bundle(claude_dir, repo_dir)
    _install_runtime_bundle(codex_dir, repo_dir)

    print()
    print(
        "  完成！"
        f"已安装 {claude_count} 个 Claude 命令与 {codex_count} 个 Codex 技能。"
    )
    print()
    print("  Claude Code 中可用：")
    print("  ─────────────────────────────────────")
    print("    /auto-experiment     启动 7×24 实验循环")
    print("    /experiment-status   查看实验进度")
    print("    /gpu-monitor         GPU 状态与可用性")
    print("    /daily-papers        arXiv 论文推荐")
    print("    /paper-analyze       深度论文分析")
    print("    /conf-search         会议论文检索")
    print("    /progress-report     生成进度报告")
    print("    /obsidian-sync       刷新 Obsidian 笔记")
    print()
    print("  Codex 中可用：")
    print("  ─────────────────────────────────────")
    print("    $auto-experiment     启动 7×24 实验循环")
    print("    $experiment-status   查看实验进度")
    print("    $gpu-monitor         GPU 状态与可用性")
    print("    $daily-papers        arXiv 论文推荐")
    print("    $paper-analyze       深度论文分析")
    print("    $conf-search         会议论文检索")
    print("    $progress-report     生成进度报告")
    print("    $obsidian-sync       刷新 Obsidian 笔记")
    print()
    print("  快速开始：")
    print("    1. 创建一个带 PROJECT_BRIEF.md 的项目")
    print("    2. Claude: /auto-experiment --project <路径> --gpu 0")
    print("    3. Codex: 用 $auto-experiment 走相同流程")
    print()
    print("  重启 Codex 以加载新安装的本地技能。")
    print()


def uninstall(
    claude_dir: Path = CLAUDE_DIR,
    codex_dir: Path = CODEX_DIR,
    repo_dir: Path = REPO_DIR,
):
    """移除所有已安装的技能。"""
    removed_claude = 0
    claude_commands = claude_dir / "commands"
    for skill_dir in _iter_skill_dirs(repo_dir / "skills"):
        dest = claude_commands / f"{skill_dir.name}.md"
        if dest.exists():
            dest.unlink()
            print(f"    ✗ Claude /{skill_dir.name}")
            removed_claude += 1

    removed_codex = 0
    codex_skills = codex_dir / "skills"
    for skill_dir in _iter_skill_dirs(repo_dir / "skills"):
        dest_dir = codex_skills / skill_dir.name
        if dest_dir.exists():
            marker = dest_dir / CODEX_INSTALL_MARKER
            if marker.exists():
                shutil.rmtree(dest_dir)
                print(f"    ✗ Codex ${skill_dir.name}")
                removed_codex += 1

    for home_dir, label in ((claude_dir, "Claude"), (codex_dir, "Codex")):
        deep_dir = home_dir / "deep-researcher"
        if deep_dir.exists():
            shutil.rmtree(deep_dir)
            print(f"    ✗ {label} 运行时包")

    print(
        f"\n  已移除 {removed_claude} 个 Claude 命令与 "
        f"{removed_codex} 个 Codex 技能。"
    )


if __name__ == "__main__":
    # 命令行入口：默认安装，传入 --uninstall 则卸载
    if len(sys.argv) > 1 and sys.argv[1] == "--uninstall":
        uninstall()
    else:
        install()
