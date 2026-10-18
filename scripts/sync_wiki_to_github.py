#!/usr/bin/env python3
"""Synchronize repository wiki/ directory with GitHub Wiki repository.

Google Gemini Notebook (NotebookLM) MCP Gateway
================================================
GitHub Wikis are separate Git repositories located at:
  https://github.com/<owner>/<repo>.wiki.git

This script clones or pulls the wiki repository into a temporary directory,
synchronizes all markdown documentation from the local wiki/ folder,
and pushes the updates to the master branch.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def sync_wiki(
    repo_root: Path | None = None,
    wiki_url: str = "https://github.com/wdeldaybytebuster/google-notebook-mcp.wiki.git",
    dry_run: bool = False,
) -> int:
    root = (repo_root or Path.cwd()).resolve()
    local_wiki = root / "wiki"
    if not local_wiki.is_dir():
        print(f"[!] Error: Could not locate wiki directory at {local_wiki}")
        return 1

    print(f"[*] Local wiki source: {local_wiki}")
    print(f"[*] Remote wiki repo:  {wiki_url}")

    with tempfile.TemporaryDirectory(prefix="wiki_sync_") as tmpdir:
        tmp_repo = Path(tmpdir) / "repo"
        print("[*] Cloning wiki repository...")
        clone_res = subprocess.run(
            ["git", "clone", wiki_url, str(tmp_repo)],
            capture_output=True,
            text=True,
            check=False,
        )
        if clone_res.returncode != 0:
            print(f"[!] Failed to clone wiki repository: {clone_res.stderr}")
            return 1

        print("[*] Copying updated wiki documents...")
        for src_file in local_wiki.glob("*.md"):
            dest_file = tmp_repo / src_file.name
            shutil.copy2(src_file, dest_file)
            print(f"  -> Copied {src_file.name}")

        # Also support alias files if needed
        arch_file = local_wiki / "Architecture.md"
        if arch_file.exists():
            shutil.copy2(arch_file, tmp_repo / "Architecture-and-ADRs.md")
        trouble_file = local_wiki / "Troubleshooting.md"
        if trouble_file.exists():
            shutil.copy2(trouble_file, tmp_repo / "Troubleshooting-and-FAQ.md")

        status_res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(tmp_repo),
            capture_output=True,
            text=True,
            check=False,
        )
        if not status_res.stdout.strip():
            print("[+] Wiki is already up-to-date. No changes to commit.")
            return 0

        if dry_run:
            print("[*] Dry run mode enabled. Changes detected:")
            print(status_res.stdout)
            return 0

        subprocess.run(
            ["git", "add", "."],
            cwd=str(tmp_repo),
            check=True,
        )
        commit_res = subprocess.run(
            ["git", "commit", "-m", "docs(wiki): synchronize wiki documentation from repository"],
            cwd=str(tmp_repo),
            capture_output=True,
            text=True,
            check=False,
        )
        if commit_res.returncode != 0:
            print(f"[!] Git commit failed: {commit_res.stderr}")
            return 1

        print("[*] Pushing updates to GitHub Wiki...")
        push_res = subprocess.run(
            ["git", "push", "origin", "master"],
            cwd=str(tmp_repo),
            capture_output=True,
            text=True,
            check=False,
        )
        if push_res.returncode != 0:
            print(f"[!] Git push failed: {push_res.stderr}")
            return 1

        print("[+] Successfully synchronized wiki documentation with GitHub Wiki!")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize local wiki/ documentation with GitHub Wiki.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="Path to repository root")
    parser.add_argument(
        "--wiki-url",
        type=str,
        default="https://github.com/wdeldaybytebuster/google-notebook-mcp.wiki.git",
        help="GitHub Wiki git URL",
    )
    parser.add_argument("--dry-run", action="store_true", help="Inspect changes without committing or pushing")
    args = parser.parse_args()
    return sync_wiki(repo_root=args.repo_root, wiki_url=args.wiki_url, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
