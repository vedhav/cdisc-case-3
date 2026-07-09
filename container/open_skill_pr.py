"""Open a PR that appends a distilled lesson to the draft-custom-programs skill.

Runs as the `open-skill-pr` script step in the cdisc-case-3 workflow — the
deterministic half of the self-learning loop. Triggered after the human approves
the drafted custom programs; consumes the upstream `propose-skill-update` agent
output. Idempotent under retry (branch + PR creation both detect existing state
and short-circuit).

Inputs:
  /output/input.json
    Carries the upstream `propose-skill-update` step output:
      hasLessons:           bool
      lessonAppendMarkdown: string   # the exact block to append; "" when none
      prTitle:              string
      prBody:               string
      summary:              string
    plus runId (top-level or under `variables` / env).

  env:
    GITHUB_TOKEN  — token with `contents:write` + `pull-requests:write` on SKILL_REPO
    SKILL_REPO    — `<owner>/<repo>` the skill lives in (e.g. vedhav/cdisc-case-3)
    RUN_ID        — short identifier for the branch name; falls back to runId /
                    processInstanceId from /output/input.json

Outputs:
  /output/result.json
    {
      "prCreated": bool,
      "prUrl":     string | null,   # null when skipped
      "branch":    string | null,
      "reason":    string | null    # filled when skipped
    }

Behaviour:
  - hasLessons false OR lessonAppendMarkdown empty  -> no clone, prCreated=false
  - Otherwise: fresh shallow clone of SKILL_REPO main, append the lesson block to
    the lessons-learned.md, branch `skill-lesson/<runId>`, commit as Mediforce
    Bot, push (force on retry), and POST the PR via the GitHub REST API. A 422
    (PR already exists for the head) is resolved by fetching the existing PR.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

OUTPUT = Path(os.environ.get("OUTPUT_DIR", "/output"))
CLONE_DIR = Path(os.environ.get("CLONE_DIR", "/tmp/skill-repo"))
LESSONS_FILE = "plugins/cdisc-case-3/skills/draft-custom-programs/references/lessons-learned.md"
COMMIT_AUTHOR_NAME = "Mediforce Bot"
COMMIT_AUTHOR_EMAIL = "bot@mediforce.ai"


def write_result(payload: dict) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def fail(message: str) -> None:
    """Write a failure result.json and exit non-zero."""
    write_result({"prCreated": False, "prUrl": None, "branch": None, "reason": f"error: {message}"})
    print(f"open_skill_pr: {message}", file=sys.stderr)
    sys.exit(1)


def skip(branch: str | None, reason: str) -> None:
    """Write a clean no-PR result and exit 0."""
    write_result({"prCreated": False, "prUrl": None, "branch": branch, "reason": reason})
    print(f"open_skill_pr: {reason} — skipping PR", file=sys.stderr)
    sys.exit(0)


def run(cmd: list[str], cwd: Path | None = None, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a command and capture output. Surfaces stderr on failure."""
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        env=env if env is not None else os.environ.copy(),
    )
    if check and result.returncode != 0:
        sys.stderr.write(f"$ {' '.join(cmd)}\n{result.stdout}{result.stderr}\n")
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    return result


def append_lesson(repo_dir: Path, lesson_md: str) -> bool:
    """Append the lesson block to the lessons file inside repo_dir.

    Returns True if the file content changed, False if the block was already
    present at the tail (idempotent under retry). Pure filesystem work — no git,
    no network — so it is unit-testable.
    """
    target = repo_dir / LESSONS_FILE
    if not target.exists():
        raise FileNotFoundError(f"{LESSONS_FILE} missing in repo — cannot append lesson")
    current = target.read_text(encoding="utf-8")
    block = lesson_md if lesson_md.startswith("\n") else "\n" + lesson_md
    if current.endswith(block):
        return False
    if not current.endswith("\n"):
        current += "\n"
    target.write_text(current + block, encoding="utf-8")
    return True


def github_api(method: str, path: str, token: str, body: dict | None = None) -> tuple[int, dict | list | None]:
    """Issue a request to api.github.com using urllib (no extra deps)."""
    url = f"https://api.github.com{path}"
    data_bytes = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data_bytes, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data_bytes is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            payload_text = resp.read().decode("utf-8")
            return resp.status, json.loads(payload_text) if payload_text else None
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8") if exc.fp else ""
        try:
            return exc.code, json.loads(body_text) if body_text else None
        except json.JSONDecodeError:
            return exc.code, {"error": body_text}


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    remote = os.environ.get("SKILL_REPO", "").strip()
    if not token:
        fail("GITHUB_TOKEN not set")
    if not remote or "/" not in remote:
        fail("SKILL_REPO must be set to '<owner>/<repo>'")

    input_path = OUTPUT / "input.json"
    if not input_path.exists():
        fail("/output/input.json missing — upstream step did not produce input")

    try:
        step_input = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"could not parse /output/input.json: {exc}")
        return  # unreachable, satisfies type checker

    run_id = (
        os.environ.get("RUN_ID")
        or step_input.get("runId")
        or step_input.get("processInstanceId")
        or ""
    )
    branch = f"skill-lesson/{run_id}" if run_id else "skill-lesson/adhoc"

    lesson_md = (step_input.get("lessonAppendMarkdown") or "").strip()
    if not step_input.get("hasLessons") or not lesson_md:
        skip(branch, "no-lessons")
        return

    pr_title = step_input.get("prTitle") or f"draft-custom-programs: lesson from run {run_id}"
    pr_body = step_input.get("prBody") or "Auto-generated by the cdisc-case-3 self-learning loop."

    if CLONE_DIR.exists():
        shutil.rmtree(CLONE_DIR)
    CLONE_DIR.mkdir(parents=True)

    clone_url = f"https://x-access-token:{token}@github.com/{remote}.git"
    try:
        run(["git", "clone", "--depth", "1", clone_url, str(CLONE_DIR)])
    except subprocess.CalledProcessError as exc:
        fail(f"git clone failed: {exc.stderr.strip()[-400:]}")

    try:
        changed = append_lesson(CLONE_DIR, "\n" + lesson_md + "\n")
    except FileNotFoundError as exc:
        fail(str(exc))
        return
    if not changed:
        skip(branch, "lesson-already-present")
        return

    run(["git", "checkout", "-b", branch], cwd=CLONE_DIR)

    git_env = os.environ.copy()
    git_env["GIT_AUTHOR_NAME"] = COMMIT_AUTHOR_NAME
    git_env["GIT_AUTHOR_EMAIL"] = COMMIT_AUTHOR_EMAIL
    git_env["GIT_COMMITTER_NAME"] = COMMIT_AUTHOR_NAME
    git_env["GIT_COMMITTER_EMAIL"] = COMMIT_AUTHOR_EMAIL

    run(["git", "add", LESSONS_FILE], cwd=CLONE_DIR, env=git_env)
    diff_check = run(["git", "diff", "--cached", "--quiet"], cwd=CLONE_DIR, check=False, env=git_env)
    if diff_check.returncode == 0:
        skip(branch, "no-staged-changes")
        return

    run(["git", "commit", "-m", f"draft-custom-programs lesson from run {run_id}"], cwd=CLONE_DIR, env=git_env)
    run(["git", "push", "--force", "-u", "origin", branch], cwd=CLONE_DIR, env=git_env)

    create_status, create_body = github_api(
        "POST",
        f"/repos/{remote}/pulls",
        token,
        {"title": pr_title, "body": pr_body, "head": branch, "base": "main"},
    )
    if create_status == 201 and isinstance(create_body, dict):
        pr_url = create_body.get("html_url")
    elif create_status == 422:
        owner = remote.split("/")[0]
        list_status, list_body = github_api(
            "GET",
            f"/repos/{remote}/pulls?head={owner}:{branch}&state=open",
            token,
        )
        if list_status == 200 and isinstance(list_body, list) and list_body:
            pr_url = list_body[0].get("html_url")
        else:
            fail(f"PR creation returned 422 and no existing PR found (list status {list_status})")
            return
    else:
        fail(f"PR creation failed: status {create_status}, body {create_body!r}")
        return

    write_result({"prCreated": True, "prUrl": pr_url, "branch": branch, "reason": None})
    print(f"open_skill_pr: opened {pr_url}", file=sys.stderr)


if __name__ == "__main__":
    main()
