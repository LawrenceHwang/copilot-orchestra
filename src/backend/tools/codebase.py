"""
Codebase file system tools for Copilot agents.

Security is the primary concern:
- All paths are validated against a single allowed root
- Path traversal is blocked via Path.resolve() + relative_to()
- File size is capped at 1 MB to prevent context overflow
- Symlinks that escape the root are blocked
- Subprocess calls use list args (no shell=True, no injection vector)

Large-repo support:
- list_directory uses git ls-files when in a git repo (respects .gitignore)
- Hardcoded _SKIP_DIRS for non-git fallback (node_modules, __pycache__, etc.)
- MAX_DIRECTORY_FILES cap with truncation notice
- grep_codebase tool for content search (rg → git grep → Python fallback)
- git_diff_file tool for targeted per-file diffs
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from copilot import define_tool
from copilot.types import Tool
from pydantic import BaseModel, Field

from backend.logging_config import get_logger

logger = get_logger("codebase_tools")

MAX_FILE_SIZE_BYTES = 1024 * 1024  # 1 MB
MAX_GIT_DIFF_BYTES = 50_000
MAX_DIRECTORY_DEPTH = 5
MAX_DIRECTORY_FILES = 300  # total entries before truncation
MAX_GREP_OUTPUT_BYTES = 20_000  # bytes before grep output is truncated

# Agent guardrail thresholds
_TOOL_CALL_NUDGE_AT = 15   # append a "do you have enough?" nudge after this many calls
_FILE_READ_WARN_AT = 20    # append a soft warning after this many distinct files read

# Common large/generated directories to skip in non-git fallback mode.
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        "target",
        "vendor",
        ".gradle",
        ".idea",
        "coverage",
        ".nyc_output",
        ".cache",
        ".tox",
        "eggs",
    }
)


# ── Custom exceptions ─────────────────────────────────────────────────────────


class PathNotAllowedError(PermissionError):
    """Raised when a path is outside the allowed root."""


class FileTooLargeError(ValueError):
    """Raised when a file exceeds the size limit."""


class DirectoryTooDeepError(ValueError):
    """Raised when max_depth exceeds the allowed maximum."""


# ── Registry ──────────────────────────────────────────────────────────────────


class CodebaseToolRegistry:
    """
    Holds the allowed root and provides safe file operations.

    One registry per review — the root is locked to the requested codebase path.
    """

    def __init__(self, allowed_root: str | Path) -> None:
        self._root = Path(allowed_root).resolve()
        if not self._root.is_dir():
            raise ValueError(f"Allowed root is not a directory: {self._root}")
        logger.info("CodebaseToolRegistry initialised", root=str(self._root))

    def resolve_safe(self, path: str) -> Path:
        """
        Resolve path and verify it is within the allowed root.

        Raises PathNotAllowedError if the resolved path escapes the root.
        This blocks both directory traversal (../../etc) and symlink escapes.
        """
        # Many models emit root-relative paths (e.g. "src/app.py") while
        # others emit absolute paths. Support both safely.
        raw_path = path.strip()
        candidate: Path
        if raw_path in {"", "."}:
            candidate = self._root
        else:
            candidate = Path(raw_path).expanduser()
            if not candidate.is_absolute():
                candidate = self._root / candidate

        try:
            resolved = candidate.resolve()
        except (OSError, ValueError) as exc:
            raise PathNotAllowedError(f"Invalid path: {exc}") from exc

        try:
            resolved.relative_to(self._root)
        except ValueError:
            raise PathNotAllowedError(f"Path '{path}' is outside the allowed root '{self._root}'")
        return resolved

    def read_file(self, path: str) -> str:
        """
        Read and return the text contents of a file.

        Raises:
            PathNotAllowedError: path outside allowed root
            FileNotFoundError: file does not exist
            IsADirectoryError: path is a directory
            FileTooLargeError: file exceeds 1 MB
        """
        safe = self.resolve_safe(path)

        if safe.is_dir():
            raise IsADirectoryError(f"'{path}' is a directory, not a file")
        if not safe.exists():
            raise FileNotFoundError(f"File not found: {path}")

        size = safe.stat().st_size
        if size > MAX_FILE_SIZE_BYTES:
            raise FileTooLargeError(
                f"File '{path}' is {size} bytes — exceeds {MAX_FILE_SIZE_BYTES} byte limit"
            )

        content = safe.read_text(encoding="utf-8", errors="replace")
        logger.debug("read_file", path=str(safe), size=size)
        return content

    def list_directory(self, path: str, max_depth: int = 3) -> str:
        """
        Return a text tree of the directory contents up to max_depth.

        When inside a git repo, uses `git ls-files` to produce a .gitignore-aware
        listing. Falls back to a filesystem walk filtered by _SKIP_DIRS otherwise.
        Both paths enforce MAX_DIRECTORY_FILES and append a truncation notice if hit.

        Raises:
            PathNotAllowedError: path outside allowed root
            NotADirectoryError: path is not a directory
            DirectoryTooDeepError: max_depth > MAX_DIRECTORY_DEPTH
        """
        if max_depth > MAX_DIRECTORY_DEPTH:
            raise DirectoryTooDeepError(
                f"max_depth {max_depth} exceeds maximum of {MAX_DIRECTORY_DEPTH}"
            )

        safe = self.resolve_safe(path)
        if not safe.is_dir():
            raise NotADirectoryError(f"'{path}' is not a directory")

        lines: list[str] = []
        truncated = False

        git_paths = _git_ls_files(safe)
        if git_paths is not None:
            lines, remaining = _build_tree_from_git_paths(git_paths, max_depth, MAX_DIRECTORY_FILES)
            truncated = remaining > 0
            truncation_suffix = (
                f"\n[... {remaining} more files not shown — use grep_codebase to search]"
                if truncated
                else ""
            )
        else:
            counter = [0]
            complete = _build_tree(safe, safe, max_depth, 0, lines, counter)
            truncated = not complete
            truncation_suffix = (
                "\n[... more entries not shown — use grep_codebase to search]" if truncated else ""
            )

        result = "\n".join(lines) + truncation_suffix
        logger.debug("list_directory", path=str(safe), lines=len(lines), truncated=truncated)
        return result

    def grep_codebase(self, pattern: str, glob: str = "", max_results: int = 50) -> str:
        """
        Search file contents for a regex pattern.

        Tries rg (ripgrep) first, then git grep, then a pure-Python fallback.
        All subprocess calls use list-form args — no shell injection possible.
        Output is capped at MAX_GREP_OUTPUT_BYTES.

        Returns `file:line: content` lines, or '[no matches found]'.
        """
        for searcher in (
            lambda: self._grep_with_rg(pattern, glob, max_results),
            lambda: self._grep_with_git(pattern, glob, max_results),
        ):
            result = searcher()
            if result is not None:
                logger.debug("grep_codebase", pattern=pattern, glob=glob, backend="external")
                return result

        result = self._grep_python(pattern, glob, max_results)
        logger.debug("grep_codebase", pattern=pattern, glob=glob, backend="python")
        return result

    def _grep_with_rg(self, pattern: str, glob: str, max_results: int) -> str | None:
        cmd = ["rg", "--line-number", "--no-heading", f"--max-count={max_results}"]
        if glob:
            cmd += ["--glob", glob]
        cmd += [pattern, "."]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self._root),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            # rg exit codes: 0=matches, 1=no matches, 2=error
            if result.returncode == 2:
                return None
            return _cap_grep_output(result.stdout)
        except FileNotFoundError:
            return None  # rg not installed
        except subprocess.TimeoutExpired:
            return "[grep timed out]"

    def _grep_with_git(self, pattern: str, glob: str, max_results: int) -> str | None:
        cmd = ["git", "grep", "-n", f"--max-count={max_results}", "--", pattern]
        if glob:
            cmd.append(glob)
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self._root),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            # 128 = not a git repo or fatal error; treat as unavailable
            if result.returncode == 128:
                return None
            return _cap_grep_output(result.stdout)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def _grep_python(self, pattern: str, glob: str, max_results: int) -> str:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            return f"[invalid regex: {exc}]"

        matches: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self._root):
            # Skip large/generated dirs in-place so os.walk doesn't descend
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
            for filename in sorted(filenames):
                if glob and not fnmatch.fnmatch(filename, glob):
                    continue
                filepath = Path(dirpath) / filename
                try:
                    text = filepath.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for lineno, line in enumerate(text.splitlines(), 1):
                    if compiled.search(line):
                        rel = filepath.relative_to(self._root)
                        matches.append(f"{rel}:{lineno}: {line.rstrip()}")
                        if len(matches) >= max_results:
                            return _cap_grep_output("\n".join(matches))

        return _cap_grep_output("\n".join(matches))

    def git_diff(self, path: str, base: str = "HEAD") -> str:
        """
        Return the git diff for the repository at path.

        The base argument is passed directly to git — it is never shell-expanded
        because we use list-form subprocess args.

        Returns empty string if not a git repo or no changes.
        """
        safe = self.resolve_safe(path)

        # Validate base is a simple ref (no shell metacharacters)
        if not _is_safe_git_ref(base):
            raise ValueError(f"Unsafe git ref: {base!r}")

        try:
            result = subprocess.run(
                ["git", "diff", base],
                cwd=str(safe),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except FileNotFoundError:
            return "[git not available]"
        except subprocess.TimeoutExpired:
            return "[git diff timed out]"

        if result.returncode not in (0, 1):
            logger.warning("git diff failed", stderr=result.stderr[:500])
            return f"[git diff error: {result.stderr[:200]}]"

        output = result.stdout
        if len(output) > MAX_GIT_DIFF_BYTES:
            output = output[:MAX_GIT_DIFF_BYTES] + "\n[...truncated]"

        logger.debug("git_diff", path=str(safe), base=base, size=len(output))
        return output

    def git_diff_file(self, path: str, file: str, base: str = "HEAD") -> str:
        """
        Return the git diff for a single file within the repository.

        Validates both the repo root and the target file path against the
        allowed root, preventing path traversal via the `file` argument.
        """
        safe_root = self.resolve_safe(path)

        if not _is_safe_git_ref(base):
            raise ValueError(f"Unsafe git ref: {base!r}")

        # Resolve and validate the target file relative to the repo root
        safe_file = self.resolve_safe(str(safe_root / file))
        rel_file = str(safe_file.relative_to(safe_root))

        try:
            result = subprocess.run(
                ["git", "diff", base, "--", rel_file],
                cwd=str(safe_root),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except FileNotFoundError:
            return "[git not available]"
        except subprocess.TimeoutExpired:
            return "[git diff timed out]"

        if result.returncode not in (0, 1):
            logger.warning("git diff file failed", file=rel_file, stderr=result.stderr[:500])
            return f"[git diff error: {result.stderr[:200]}]"

        output = result.stdout
        if len(output) > MAX_GIT_DIFF_BYTES:
            output = output[:MAX_GIT_DIFF_BYTES] + "\n[...truncated]"

        logger.debug(
            "git_diff_file", path=str(safe_root), file=rel_file, base=base, size=len(output)
        )
        return output


# ── Pydantic parameter models ─────────────────────────────────────────────────


class ReadFileParams(BaseModel):
    path: str = Field(
        description=(
            "File path to read. Accepts either an absolute path or a path "
            "relative to the review root (e.g. 'src/main.py')."
        )
    )


class ListDirectoryParams(BaseModel):
    path: str = Field(
        default=".",
        description=(
            "Directory path to list. Accepts absolute or review-root-relative "
            "paths. Defaults to the review root when omitted."
        ),
    )
    max_depth: int = Field(
        default=3,
        ge=1,
        le=MAX_DIRECTORY_DEPTH,
        description=f"Recursion depth (1-{MAX_DIRECTORY_DEPTH})",
    )


class GrepCodebaseParams(BaseModel):
    pattern: str = Field(description="Regex pattern to search for in file contents")
    glob: str = Field(
        default="",
        description="Optional file glob filter, e.g. '*.py', '*.ts', '**/*.sql'",
    )
    max_results: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of matching lines to return (1-200)",
    )


class GitDiffParams(BaseModel):
    path: str = Field(
        default=".",
        description=(
            "Path to the git repository root. Accepts absolute or "
            "review-root-relative paths. Defaults to the review root."
        ),
    )
    base: str = Field(
        default="HEAD",
        description="Git ref to diff against (e.g. HEAD, main, abc1234)",
    )


class GitDiffFileParams(BaseModel):
    path: str = Field(
        default=".",
        description=(
            "Path to the git repository root. Accepts absolute or "
            "review-root-relative paths. Defaults to the review root."
        ),
    )
    file: str = Field(description="Relative path of the file to diff within the repository")
    base: str = Field(
        default="HEAD",
        description="Git ref to diff against (e.g. HEAD, main, abc1234)",
    )


# ── Tool builder ──────────────────────────────────────────────────────────────


def build_codebase_tools(codebase_path: str, start_time: float | None = None) -> list[Tool]:
    """
    Build codebase tools locked to the given root path.

    Returns a list of Tool objects ready to pass to SessionConfig.
    Each call creates a new registry and fresh tracking state — call once
    per agent so that elapsed time and file-read counts are per-agent.

    Optional start_time enables runtime guardrail annotations on every
    tool result:
      - Elapsed time footer (⏱ Elapsed: Xs) so the agent can self-regulate.
      - Soft warning after _FILE_READ_WARN_AT distinct files have been read.
      - Nudge after _TOOL_CALL_NUDGE_AT total tool calls asking whether the
        agent has enough context to proceed.

    Tools provided (5 total):
      - read_file: read a single file (1 MB cap)
      - list_directory: gitignore-aware directory tree (300-entry cap)
      - grep_codebase: regex search across file contents
      - git_diff: full repo diff against a ref
      - git_diff_file: single-file diff against a ref
    """
    registry = CodebaseToolRegistry(allowed_root=codebase_path)

    # Per-agent mutable tracking state (created fresh per build_codebase_tools call).
    _files_read: set[str] = set()
    _call_count: list[int] = [0]  # list so inner functions can mutate it

    def _annotate(result: str, file_path: str | None = None) -> str:
        """Append guardrail annotations to a tool result."""
        _call_count[0] += 1
        if file_path:
            _files_read.add(file_path)

        notes: list[str] = []

        if start_time is not None:
            elapsed = int(time.monotonic() - start_time)
            notes.append(f"⏱ Elapsed: {elapsed}s")

        if file_path and len(_files_read) == _FILE_READ_WARN_AT:
            notes.append(
                f"⚠ You have now read {len(_files_read)} distinct files. "
                "Consider whether you have enough context to proceed rather than reading more."
            )

        if _call_count[0] == _TOOL_CALL_NUDGE_AT:
            notes.append(
                f"ℹ You have made {_call_count[0]} tool calls. "
                "Do you have enough information to write your review / submit your plan? "
                "If yes, do so now."
            )

        if not notes:
            return result
        return result + "\n\n---\n" + " | ".join(notes)

    @define_tool(
        description=(
            "Read the text contents of a file in the codebase. "
            "Returns the file content as a string."
        )
    )
    def read_file(params: ReadFileParams) -> str:
        result = registry.read_file(params.path)
        return _annotate(result, file_path=params.path)

    @define_tool(
        description=(
            "List files and directories in a codebase path as an indented tree. "
            "Respects .gitignore when inside a git repo. "
            "Use to understand project structure before reading files. "
            "If output is truncated, use grep_codebase to find specific files."
        )
    )
    def list_directory(params: ListDirectoryParams) -> str:
        result = registry.list_directory(params.path, params.max_depth)
        return _annotate(result)

    @define_tool(
        description=(
            "Search file contents for a regex pattern. "
            "Returns matching lines as 'file:line: content'. "
            "Use this to find relevant files in large repos instead of browsing directories. "
            "Supports an optional glob filter (e.g. '*.py', '*.ts')."
        )
    )
    def grep_codebase(params: GrepCodebaseParams) -> str:
        result = registry.grep_codebase(params.pattern, params.glob, params.max_results)
        return _annotate(result)

    @define_tool(
        description=(
            "Get the full git diff for the repository against a ref. "
            "Useful for understanding all recent changes. "
            "For large diffs, use git_diff_file to focus on a single file."
        )
    )
    def git_diff(params: GitDiffParams) -> str:
        result = registry.git_diff(params.path, params.base)
        return _annotate(result)

    @define_tool(
        description=(
            "Get the git diff for a single file within the repository. "
            "Use this instead of git_diff when you only need changes for one file."
        )
    )
    def git_diff_file(params: GitDiffFileParams) -> str:
        result = registry.git_diff_file(params.path, params.file, params.base)
        return _annotate(result)

    return [read_file, list_directory, grep_codebase, git_diff, git_diff_file]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_safe_git_ref(ref: str) -> bool:
    """Check that a git ref contains only safe characters."""
    return bool(re.match(r"^[a-zA-Z0-9_.~^/\-]+$", ref))


def _cap_grep_output(output: str) -> str:
    """Truncate grep output to MAX_GREP_OUTPUT_BYTES and normalise empty result."""
    if not output.strip():
        return "[no matches found]"
    if len(output) > MAX_GREP_OUTPUT_BYTES:
        output = output[:MAX_GREP_OUTPUT_BYTES] + "\n[...truncated]"
    return output


def _is_git_repo(path: Path) -> bool:
    """Return True if path is inside a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=str(path),
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _git_ls_files(root: Path) -> list[str] | None:
    """
    Return relative file paths from git ls-files, or None on failure.

    Lists tracked files plus untracked files not excluded by .gitignore.
    Returns None when root is not a git repo or git is unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            return None
        paths = [p for p in result.stdout.splitlines() if p]
        return paths if paths else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _build_tree_from_git_paths(
    paths: list[str],
    max_depth: int,
    max_files: int,
) -> tuple[list[str], int]:
    """
    Reconstruct an indented directory tree from a flat list of relative paths.

    Filters to max_depth levels, sorts dirs before files at each level,
    and stops after max_files total entries. Returns (lines, remaining_file_count).
    """
    # Filter paths that are within the requested depth
    depth_filtered = [p for p in paths if len(Path(p).parts) <= max_depth]

    # Build a nested dict: dir_name -> {subdir_name -> {...}, "__files__": [...]}
    tree: dict[str, Any] = {}
    for p in depth_filtered:
        parts = Path(p).parts
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node.setdefault("__files__", []).append(parts[-1])

    lines: list[str] = []
    total = [0]  # mutable int for recursive mutation

    def render(node: dict, depth: int) -> bool:
        """Render node recursively. Returns False when cap is hit."""
        dirs = sorted(k for k in node if k != "__files__")
        files = sorted(node.get("__files__", []))
        indent = "  " * depth

        for d in dirs:
            if total[0] >= max_files:
                return False
            lines.append(f"{indent}{d}/")
            total[0] += 1
            if not render(node[d], depth + 1):
                return False

        for f in files:
            if total[0] >= max_files:
                return False
            lines.append(f"{indent}{f}")
            total[0] += 1

        return True

    complete = render(tree, 0)
    remaining = len(depth_filtered) - total[0] if not complete else 0
    return lines, remaining


def _build_tree(
    root: Path,
    current: Path,
    max_depth: int,
    depth: int,
    lines: list[str],
    counter: list[int],
) -> bool:
    """
    Recursively build directory tree lines (non-git fallback).

    Skips hidden files, symlinks, and directories in _SKIP_DIRS.
    Returns False when MAX_DIRECTORY_FILES is hit.
    """
    indent = "  " * depth
    try:
        entries = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name))
    except PermissionError:
        lines.append(f"{indent}[permission denied]")
        return True

    for entry in entries:
        if counter[0] >= MAX_DIRECTORY_FILES:
            return False
        if entry.name.startswith("."):
            continue
        if entry.name in _SKIP_DIRS:
            continue
        if entry.is_symlink():
            lines.append(f"{indent}{entry.name} -> [symlink]")
            counter[0] += 1
            continue
        if entry.is_dir():
            lines.append(f"{indent}{entry.name}/")
            counter[0] += 1
            if depth < max_depth - 1:
                if not _build_tree(root, entry, max_depth, depth + 1, lines, counter):
                    return False
        else:
            lines.append(f"{indent}{entry.name}")
            counter[0] += 1

    return True
