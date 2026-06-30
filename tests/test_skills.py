"""
Validation for the OKX AI skill pack (skills/*/SKILL.md).

Pins the skill format and — critically — re-asserts the analysis-only invariant at
the skill layer: every skill must reference a read-only RUNECLAW MCP tool and must
not reference any execution path. Pure stdlib so it always runs; the optional
cross-check against RUNECLAW's live catalogue skips if the submodule is absent.
"""

from __future__ import annotations

import os

import pytest

_SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")

# skill directory name -> the read-only MCP tool it fronts
_SKILLS = {
    "runeclaw-shield": "runeclaw_shield",
    "runeclaw-analyze": "runeclaw_analyze",
    "runeclaw-quant": "runeclaw_quant",
}

# Tokens that would indicate an execution path leaked into a skill.
_EXECUTION_MARKERS = ("runeclaw_execute", "execute_paper_trade", "confirm_trade")


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse simple single-line `key: value` YAML frontmatter and return (meta, body)."""
    assert text.startswith("---\n"), "SKILL.md must start with a YAML frontmatter block"
    end = text.index("\n---", 4)
    block = text[4:end]
    meta: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    body = text[end + len("\n---"):]
    return meta, body


def _load(skill_dir: str) -> tuple[dict[str, str], str]:
    path = os.path.join(_SKILLS_DIR, skill_dir, "SKILL.md")
    with open(path, encoding="utf-8") as fh:
        return _parse_frontmatter(fh.read())


@pytest.mark.parametrize("skill_dir,tool", sorted(_SKILLS.items()))
class TestSkillManifest:
    def test_name_matches_directory(self, skill_dir, tool):
        meta, _ = _load(skill_dir)
        assert meta.get("name") == skill_dir

    def test_description_present_and_within_1024_chars(self, skill_dir, tool):
        meta, _ = _load(skill_dir)
        desc = meta.get("description", "")
        assert desc, "description is required"
        assert len(desc) <= 1024, f"description is {len(desc)} chars (>1024)"

    def test_references_its_readonly_tool(self, skill_dir, tool):
        _, body = _load(skill_dir)
        assert tool in body, f"{skill_dir} must document its MCP tool '{tool}'"

    def test_no_execution_path_referenced(self, skill_dir, tool):
        meta, body = _load(skill_dir)
        blob = (meta.get("description", "") + "\n" + body).lower()
        for marker in _EXECUTION_MARKERS:
            assert marker not in blob, f"{skill_dir} references execution marker '{marker}'"


def test_every_skill_dir_is_registered():
    """No stray skill directory escapes the validated set above."""
    dirs = {
        d
        for d in os.listdir(_SKILLS_DIR)
        if os.path.isdir(os.path.join(_SKILLS_DIR, d))
    }
    assert dirs == set(_SKILLS), f"unregistered skill dirs: {dirs ^ set(_SKILLS)}"


def test_skills_front_only_readonly_catalogue_tools():
    """Cross-check: each skill's tool is a real, read-only RUNECLAW MCP tool (base
    or extended), and none is the (unexposed) execution tool. Skips if the submodule
    is absent."""
    server = pytest.importorskip("bot.mcp.server")
    from runeclaw_okx.extended_server import EXTENDED_TOOLS

    catalogue = {t.mcp_name for t in server.TOOL_CATALOGUE} | {
        t["mcp_name"] for t in EXTENDED_TOOLS
    }
    assert "runeclaw_execute" not in catalogue
    for tool in _SKILLS.values():
        assert tool in catalogue, f"skill tool '{tool}' is not in the MCP catalogue"
