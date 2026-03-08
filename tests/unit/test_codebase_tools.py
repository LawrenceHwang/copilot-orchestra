"""
Unit tests for codebase file tools — written BEFORE implementation (TDD).

Security is the primary concern: path traversal prevention, allowed root enforcement,
file size limits, and safe directory listing.

Large-repo tests cover:
- _SKIP_DIRS filtering in non-git fallback mode
- MAX_DIRECTORY_FILES cap with truncation notice
- git-aware listing via _git_ls_files
- grep_codebase tool (pattern search, glob filter, no-match, output cap)
- git_diff_file tool (per-file diff, path safety)
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from copilot.types import ToolInvocation, ToolResult

from backend.tools.codebase import (
    MAX_DIRECTORY_FILES,
    MAX_GREP_OUTPUT_BYTES,
    CodebaseToolRegistry,
    DirectoryTooDeepError,
    FileTooLargeError,
    PathNotAllowedError,
    _build_tree_from_git_paths,
    build_codebase_tools,
)


@pytest.fixture
def registry(tmp_codebase: Path) -> CodebaseToolRegistry:
    return CodebaseToolRegistry(allowed_root=tmp_codebase)


def assert_tool_result(
    result: ToolResult, *, result_type: str, text_contains: str | None = None
) -> None:
    assert isinstance(result, ToolResult)
    assert result.result_type == result_type
    if text_contains is not None:
        assert text_contains in result.text_result_for_llm


class TestPathValidation:
    def test_path_within_root_is_allowed(self, registry, tmp_codebase):
        path = registry.resolve_safe(str(tmp_codebase / "src" / "backend" / "auth.py"))
        assert path == (tmp_codebase / "src" / "backend" / "auth.py").resolve()

    def test_path_outside_root_raises(self, registry):
        with pytest.raises(PathNotAllowedError):
            registry.resolve_safe("/etc/passwd")

    def test_path_traversal_raises(self, registry, tmp_codebase):
        traversal = str(tmp_codebase / "src" / ".." / ".." / "etc" / "passwd")
        with pytest.raises(PathNotAllowedError):
            registry.resolve_safe(traversal)

    def test_symlink_escaping_root_raises(self, registry, tmp_codebase, tmp_path):
        # Create a symlink inside the codebase pointing outside
        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("secret")
        link = tmp_codebase / "evil_link"
        link.symlink_to(outside_file)
        with pytest.raises(PathNotAllowedError):
            registry.resolve_safe(str(link))

    def test_root_itself_is_allowed(self, registry, tmp_codebase):
        path = registry.resolve_safe(str(tmp_codebase))
        assert path == tmp_codebase.resolve()

    def test_root_relative_path_is_allowed(self, registry, tmp_codebase):
        path = registry.resolve_safe("src/backend/auth.py")
        assert path == (tmp_codebase / "src" / "backend" / "auth.py").resolve()

    def test_dot_path_resolves_to_root(self, registry, tmp_codebase):
        path = registry.resolve_safe(".")
        assert path == tmp_codebase.resolve()


class TestReadFile:
    def test_read_existing_file(self, registry, tmp_codebase):
        result = registry.read_file(str(tmp_codebase / "README.md"))
        assert "Test Repo" in result

    def test_read_nonexistent_file_raises(self, registry, tmp_codebase):
        with pytest.raises(FileNotFoundError):
            registry.read_file(str(tmp_codebase / "nonexistent.py"))

    def test_read_directory_raises(self, registry, tmp_codebase):
        with pytest.raises(IsADirectoryError):
            registry.read_file(str(tmp_codebase / "src"))

    def test_read_file_outside_root_raises(self, registry):
        with pytest.raises(PathNotAllowedError):
            registry.read_file("/etc/hostname")

    def test_read_large_file_raises(self, registry, tmp_codebase):
        large_file = tmp_codebase / "large.txt"
        large_file.write_bytes(b"x" * (1024 * 1024 + 1))  # > 1 MB
        with pytest.raises(FileTooLargeError):
            registry.read_file(str(large_file))

    def test_read_file_at_exactly_1mb_is_ok(self, registry, tmp_codebase):
        ok_file = tmp_codebase / "ok.txt"
        ok_file.write_bytes(b"x" * (1024 * 1024))  # exactly 1 MB
        result = registry.read_file(str(ok_file))
        assert len(result) == 1024 * 1024

    def test_read_existing_file_with_root_relative_path(self, registry):
        result = registry.read_file("README.md")
        assert "Test Repo" in result


class TestListDirectory:
    def test_list_directory_returns_tree(self, registry, tmp_codebase):
        result = registry.list_directory(str(tmp_codebase))
        assert "src" in result
        assert "README.md" in result

    def test_list_directory_outside_root_raises(self, registry):
        with pytest.raises(PathNotAllowedError):
            registry.list_directory("/tmp")

    def test_list_file_raises(self, registry, tmp_codebase):
        with pytest.raises(NotADirectoryError):
            registry.list_directory(str(tmp_codebase / "README.md"))

    def test_max_depth_respected(self, registry, tmp_codebase):
        # Create deep nesting
        deep = tmp_codebase / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "deep.txt").write_text("deep")
        result = registry.list_directory(str(tmp_codebase), max_depth=2)
        assert "deep.txt" not in result

    def test_max_depth_too_large_raises(self, registry, tmp_codebase):
        with pytest.raises(DirectoryTooDeepError):
            registry.list_directory(str(tmp_codebase), max_depth=10)

    def test_list_directory_shows_nested_files(self, registry, tmp_codebase):
        result = registry.list_directory(str(tmp_codebase), max_depth=3)
        assert "auth.py" in result

    def test_list_directory_with_root_relative_path(self, registry):
        result = registry.list_directory("src")
        assert "auth.py" in result


class TestBuildCodebaseTools:
    def test_build_returns_five_tools(self, tmp_codebase):
        tools = build_codebase_tools(str(tmp_codebase))
        assert len(tools) == 5

    def test_tool_names_are_correct(self, tmp_codebase):
        tools = build_codebase_tools(str(tmp_codebase))
        names = {t.name for t in tools}
        assert names == {
            "read_file",
            "list_directory",
            "grep_codebase",
            "git_diff",
            "git_diff_file",
        }

    def test_tools_have_descriptions(self, tmp_codebase):
        tools = build_codebase_tools(str(tmp_codebase))
        for tool in tools:
            assert tool.description, f"Tool {tool.name} has no description"

    def test_tools_have_parameters_schema(self, tmp_codebase):
        tools = build_codebase_tools(str(tmp_codebase))
        for tool in tools:
            assert tool.parameters is not None, f"Tool {tool.name} has no schema"

    async def test_read_file_tool_handler_works(self, tmp_codebase):
        tools = build_codebase_tools(str(tmp_codebase))
        read_tool = next(t for t in tools if t.name == "read_file")
        invocation = ToolInvocation(
            session_id="test",
            tool_call_id="tc-1",
            tool_name="read_file",
            arguments={"path": str(tmp_codebase / "README.md")},
        )
        result = await read_tool.handler(invocation)
        assert_tool_result(result, result_type="success", text_contains="Test Repo")

    async def test_read_file_tool_blocks_traversal(self, tmp_codebase):
        tools = build_codebase_tools(str(tmp_codebase))
        read_tool = next(t for t in tools if t.name == "read_file")
        invocation = ToolInvocation(
            session_id="test",
            tool_call_id="tc-2",
            tool_name="read_file",
            arguments={"path": "/etc/passwd"},
        )
        result = await read_tool.handler(invocation)
        # define_tool wraps errors as failure results, not exceptions
        assert_tool_result(result, result_type="failure")

    async def test_list_directory_tool_defaults_to_root_path(self, tmp_codebase):
        tools = build_codebase_tools(str(tmp_codebase))
        list_tool = next(t for t in tools if t.name == "list_directory")
        invocation = ToolInvocation(
            session_id="test",
            tool_call_id="tc-3",
            tool_name="list_directory",
            arguments={},
        )
        result = await list_tool.handler(invocation)
        assert_tool_result(result, result_type="success", text_contains="README.md")

    async def test_git_diff_tool_defaults_to_root_path(self, tmp_codebase):
        tools = build_codebase_tools(str(tmp_codebase))
        diff_tool = next(t for t in tools if t.name == "git_diff")
        invocation = ToolInvocation(
            session_id="test",
            tool_call_id="tc-4",
            tool_name="git_diff",
            arguments={},
        )
        result = await diff_tool.handler(invocation)
        # In a non-git temp dir this should still be a successful invocation
        # returning either empty output or an explicit git availability message.
        assert_tool_result(result, result_type="success")


# ── Large-repo: skip dirs and file cap (non-git fallback) ────────────────────


class TestListDirectoryLargeRepo:
    def test_skips_node_modules(self, registry, tmp_codebase):
        node_modules = tmp_codebase / "node_modules"
        node_modules.mkdir()
        (node_modules / "lodash.js").write_text("x")
        result = registry.list_directory(str(tmp_codebase))
        assert "node_modules" not in result

    def test_skips_pycache(self, registry, tmp_codebase):
        cache = tmp_codebase / "__pycache__"
        cache.mkdir()
        (cache / "foo.pyc").write_text("x")
        result = registry.list_directory(str(tmp_codebase))
        assert "__pycache__" not in result

    def test_skips_multiple_skip_dirs(self, registry, tmp_codebase):
        for d in ("dist", "build", ".venv", "vendor"):
            skip = tmp_codebase / d
            skip.mkdir()
            (skip / "file.txt").write_text("x")
        result = registry.list_directory(str(tmp_codebase))
        for d in ("dist", "build", "vendor"):
            assert d not in result

    def test_truncation_notice_when_cap_hit(self, registry, tmp_codebase):
        # Force non-git mode by patching _git_ls_files to return None
        many = tmp_codebase / "many"
        many.mkdir()
        for i in range(MAX_DIRECTORY_FILES + 10):
            (many / f"file_{i:04d}.txt").write_text("x")

        with patch("backend.tools.codebase._git_ls_files", return_value=None):
            result = registry.list_directory(str(tmp_codebase))

        assert "grep_codebase" in result
        assert "not shown" in result

    def test_no_truncation_when_under_cap(self, registry, tmp_codebase):
        with patch("backend.tools.codebase._git_ls_files", return_value=None):
            result = registry.list_directory(str(tmp_codebase))
        assert "not shown" not in result


# ── Large-repo: git-aware listing ────────────────────────────────────────────


class TestListDirectoryGitAware:
    def test_uses_git_paths_when_available(self, registry, tmp_codebase):
        fake_paths = ["src/backend/auth.py", "src/backend/main.py", "README.md"]
        with patch("backend.tools.codebase._git_ls_files", return_value=fake_paths):
            result = registry.list_directory(str(tmp_codebase))
        assert "auth.py" in result
        assert "README.md" in result

    def test_falls_back_to_fs_walk_when_not_git(self, registry, tmp_codebase):
        with patch("backend.tools.codebase._git_ls_files", return_value=None):
            result = registry.list_directory(str(tmp_codebase))
        # Should still show files from the filesystem
        assert "README.md" in result

    def test_git_paths_respect_max_depth(self, registry, tmp_codebase):
        # depth=3 means paths with at most 3 components (2 dir levels)
        fake_paths = ["README.md", "src/backend/auth.py", "src/backend/utils/helpers/deep.py"]
        with patch("backend.tools.codebase._git_ls_files", return_value=fake_paths):
            result = registry.list_directory(str(tmp_codebase), max_depth=3)
        assert "auth.py" in result
        assert "README.md" in result
        assert "deep.py" not in result  # too deep for max_depth=3

    def test_git_paths_truncation_notice(self, registry, tmp_codebase):
        # Provide more paths than MAX_DIRECTORY_FILES
        fake_paths = [f"file_{i:04d}.py" for i in range(MAX_DIRECTORY_FILES + 50)]
        with patch("backend.tools.codebase._git_ls_files", return_value=fake_paths):
            result = registry.list_directory(str(tmp_codebase))
        assert "grep_codebase" in result
        assert "not shown" in result

    def test_build_tree_from_git_paths_dirs_before_files(self):
        paths = ["README.md", "src/backend/auth.py", "src/backend/main.py", "tests/test_auth.py"]
        lines, remaining = _build_tree_from_git_paths(paths, max_depth=3, max_files=100)
        tree = "\n".join(lines)
        # directories should appear before files at the same level
        assert tree.index("src/") < tree.index("README.md")

    def test_build_tree_from_git_paths_returns_remaining(self):
        paths = [f"file_{i}.py" for i in range(20)]
        lines, remaining = _build_tree_from_git_paths(paths, max_depth=3, max_files=5)
        assert len(lines) == 5
        assert remaining == 15


# ── grep_codebase ─────────────────────────────────────────────────────────────


class TestGrepCodebase:
    def test_finds_pattern_in_file(self, registry, tmp_codebase):
        (tmp_codebase / "secret.py").write_text("password = 'hunter2'\n")
        # Force Python fallback so test doesn't depend on rg/git
        with (
            patch.object(registry, "_grep_with_rg", return_value=None),
            patch.object(registry, "_grep_with_git", return_value=None),
        ):
            result = registry.grep_codebase("password")
        assert "secret.py" in result
        assert "hunter2" in result

    def test_returns_no_matches_when_nothing_found(self, registry, tmp_codebase):
        with (
            patch.object(registry, "_grep_with_rg", return_value=None),
            patch.object(registry, "_grep_with_git", return_value=None),
        ):
            result = registry.grep_codebase("ZZZNOTPRESENTZZZ")
        assert result == "[no matches found]"

    def test_glob_filter_limits_to_file_type(self, registry, tmp_codebase):
        (tmp_codebase / "match.py").write_text("TARGET = 1\n")
        (tmp_codebase / "match.js").write_text("TARGET = 1\n")
        with (
            patch.object(registry, "_grep_with_rg", return_value=None),
            patch.object(registry, "_grep_with_git", return_value=None),
        ):
            result = registry.grep_codebase("TARGET", glob="*.py")
        assert "match.py" in result
        assert "match.js" not in result

    def test_max_results_respected_in_python_fallback(self, registry, tmp_codebase):
        # Write a file with many matching lines
        content = "\n".join(f"MARKER line {i}" for i in range(100))
        (tmp_codebase / "big.py").write_text(content)
        with (
            patch.object(registry, "_grep_with_rg", return_value=None),
            patch.object(registry, "_grep_with_git", return_value=None),
        ):
            result = registry.grep_codebase("MARKER", max_results=5)
        assert result.count("MARKER") <= 5

    def test_invalid_regex_returns_error_message(self, registry):
        with (
            patch.object(registry, "_grep_with_rg", return_value=None),
            patch.object(registry, "_grep_with_git", return_value=None),
        ):
            result = registry.grep_codebase("[unclosed")
        assert "invalid regex" in result

    def test_output_capped_at_max_bytes(self, registry, tmp_codebase):
        # Write a file whose match output exceeds MAX_GREP_OUTPUT_BYTES
        line = "A" * 200 + "\n"
        content = line * (MAX_GREP_OUTPUT_BYTES // len(line) + 10)
        (tmp_codebase / "huge.py").write_text(content)
        with (
            patch.object(registry, "_grep_with_rg", return_value=None),
            patch.object(registry, "_grep_with_git", return_value=None),
        ):
            result = registry.grep_codebase("A" * 200, max_results=200)
        assert len(result) <= MAX_GREP_OUTPUT_BYTES + len("\n[...truncated]")
        assert "truncated" in result

    def test_uses_rg_when_available(self, registry, tmp_codebase):
        mock_output = "src/backend/auth.py:10: secret = 'x'\n"
        with patch.object(registry, "_grep_with_rg", return_value=mock_output) as mock_rg:
            result = registry.grep_codebase("secret")
        mock_rg.assert_called_once()
        assert result == mock_output

    def test_falls_back_to_git_grep_when_rg_unavailable(self, registry, tmp_codebase):
        mock_output = "src/backend/auth.py:10: secret = 'x'\n"
        with (
            patch.object(registry, "_grep_with_rg", return_value=None),
            patch.object(registry, "_grep_with_git", return_value=mock_output) as mock_git,
        ):
            result = registry.grep_codebase("secret")
        mock_git.assert_called_once()
        assert result == mock_output

    def test_skips_skip_dirs_in_python_fallback(self, registry, tmp_codebase):
        nm = tmp_codebase / "node_modules" / "dep"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("MARKER = 1")
        with (
            patch.object(registry, "_grep_with_rg", return_value=None),
            patch.object(registry, "_grep_with_git", return_value=None),
        ):
            result = registry.grep_codebase("MARKER")
        assert "node_modules" not in result


# ── git_diff_file ─────────────────────────────────────────────────────────────


class TestGitDiffFile:
    def _make_git_repo(self, path: Path) -> None:
        """Initialise a minimal git repo in path with one commit."""
        subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True, check=True
        )
        subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=str(path), capture_output=True, check=True
        )

    def test_returns_diff_for_modified_file(self, registry, tmp_codebase):
        self._make_git_repo(tmp_codebase)
        (tmp_codebase / "README.md").write_text("# Changed\n")
        result = registry.git_diff_file(str(tmp_codebase), "README.md")
        assert "README.md" in result or "Changed" in result

    def test_returns_empty_for_unchanged_file(self, registry, tmp_codebase):
        self._make_git_repo(tmp_codebase)
        result = registry.git_diff_file(str(tmp_codebase), "README.md")
        assert result == ""

    def test_blocks_path_traversal_via_file_param(self, registry, tmp_codebase, tmp_path):
        outside = tmp_path / "secret.txt"
        outside.write_text("secret")
        with pytest.raises(PathNotAllowedError):
            registry.git_diff_file(str(tmp_codebase), "../../secret.txt")

    def test_rejects_unsafe_git_ref(self, registry, tmp_codebase):
        with pytest.raises(ValueError, match="Unsafe git ref"):
            registry.git_diff_file(str(tmp_codebase), "README.md", base="HEAD; rm -rf /")
