import shutil
import subprocess
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def task_dir(workspace: Path) -> Path:
    return workspace / "tasks" / "sample_task"


def create_workspace(run_id: str) -> Path:
    root = repo_root()
    destination = root / ".worktrees" / run_id
    if destination.exists():
        shutil.rmtree(destination)
    if _has_head(root):
        destination.parent.mkdir(parents=True, exist_ok=True)
        branch = f"live-{run_id}"
        completed = subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(destination), "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "git worktree add failed")
        return destination
    source = root / "tasks" / "sample_task"
    target = task_dir(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    return destination


def _has_head(root: Path) -> bool:
    if not (root / ".git").exists():
        return False
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0
