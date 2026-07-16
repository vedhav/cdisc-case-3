"""Open a PR that appends distilled lessons to one or more workflow skills.

Runs as the `open-skill-pr` script step in the cdisc-case-3 workflow — the
deterministic half of the generalized self-learning loop. Triggered after the
run's reviews; consumes the upstream `propose-skill-update` agent output, which
carries per-skill lesson blocks (feedback from any of the three review gates:
plan / specs / TLFs). Idempotent under retry (branch + PR creation both detect
existing state and short-circuit).

Inputs:
  /output/input.json
    Carries the upstream `propose-skill-update` step output:
      hasLessons: bool
      lessons:    [ { "skill": "<skill-id>", "lessonAppendMarkdown": "<block>" }, ... ]
      prTitle:    string
      prBody:     string
      summary:    string
    (Back-compat: a single top-level `lessonAppendMarkdown` for skill
    "tlf-generator" is still accepted.) Plus runId (top-level / variables / env).

  env:
    GITHUB_TOKEN  — token with contents:write + pull-requests:write on SKILL_REPO
    SKILL_REPO    — "<owner>/<repo>" the skills live in (e.g. vedhav/cdisc-case-3)
    RUN_ID        — short id for the branch name; falls back to runId /
                    processInstanceId from /output/input.json

Outputs:
  /output/result.json
    { "prCreated": bool, "prUrl": str|null, "branch": str|null,
      "skills": [<skill ids appended>], "reason": str|null }

Behaviour:
  - hasLessons false OR no non-empty lesson block -> no clone, prCreated=false
  - Otherwise: fresh shallow clone of SKILL_REPO main, append each skill's block
    to plugins/cdisc-case-3/skills/<skill>/references/lessons-learned.md, branch
    skill-lesson/<runId>, commit as Mediforce Bot, push (force on retry), and POST
    one PR via the GitHub REST API covering all touched skills. A 422 (PR already
    exists for the head) is resolved by fetching the existing PR.
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
SKILLS_ROOT = "plugins/cdisc-case-3/skills"
COMMIT_AUTHOR_NAME = "Mediforce Bot"
COMMIT_AUTHOR_EMAIL = "bot@mediforce.ai"

# Only these skills may be targeted (guards against a bad skill id writing a
# stray path). Keep in sync with the ported skills that carry a lessons file.
ALLOWED_SKILLS = {
    "tlf-planner",
    "tlf-plan-critic",
    "tlf-analysis-spec",
    "sdtm-to-adam",
    "tlf-generator",
    "traceability-builder",
}


def lessons_file_for(skill: str) -> str:
    return f"{SKILLS_ROOT}/{skill}/references/lessons-learned.md"


def write_result(payload: dict) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def fail(message: str) -> None:
    """Record the failure and exit 0 (fail-soft).

    Opening the skill-lesson PR is a non-critical side effect at the very end of
    the run — a GitHub hiccup, a token missing pull-requests:write, or an
    unparseable input must NOT bury an already-completed, human-approved TLF
    pipeline by failing its last step. We surface the reason in result.json (and
    stderr for the step log) and let the run advance to done. `continueOnError`
    would be the engine-level equivalent, but it is honoured only on `action`
    steps, not script steps — so the soft exit lives here.
    """
    write_result({"prCreated": False, "prUrl": None, "branch": None, "skills": [], "reason": f"error: {message}"})
    print(f"open_skill_pr: {message}", file=sys.stderr)
    sys.exit(0)


def skip(branch: str | None, reason: str) -> None:
    write_result({"prCreated": False, "prUrl": None, "branch": branch, "skills": [], "reason": reason})
    print(f"open_skill_pr: {reason} — skipping PR", file=sys.stderr)
    sys.exit(0)


def run(cmd: list[str], cwd: Path | None = None, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
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


def append_lesson(repo_dir: Path, rel_path: str, lesson_md: str) -> bool:
    """Append a lesson block to rel_path inside repo_dir.

    Returns True if the file content changed, False if the block was already
    present at the tail (idempotent). Creates the file (and parents) if absent —
    a newly-ported skill may not yet have a lessons file. Pure filesystem work.
    """
    target = repo_dir / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(
            f"# {Path(rel_path).parent.parent.name} — lessons learned\n\n"
            "Append-only. Added by the skill-refinement loop from reviewer feedback.\n",
            encoding="utf-8",
        )
    current = target.read_text(encoding="utf-8")
    block = lesson_md if lesson_md.startswith("\n") else "\n" + lesson_md
    if current.endswith(block):
        return False
    if not current.endswith("\n"):
        current += "\n"
    target.write_text(current + block, encoding="utf-8")
    return True


def github_api(method: str, path: str, token: str, body: dict | None = None) -> tuple[int, dict | list | None]:
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


def collect_lessons(step_input: dict) -> list[tuple[str, str]]:
    """Return [(skill, block)] from the new `lessons` list, falling back to the
    legacy single-block shape (attributed to tlf-generator)."""
    out: list[tuple[str, str]] = []
    lessons = step_input.get("lessons")
    if isinstance(lessons, list):
        for entry in lessons:
            if not isinstance(entry, dict):
                continue
            skill = (entry.get("skill") or "").strip()
            block = (entry.get("lessonAppendMarkdown") or "").strip()
            if skill in ALLOWED_SKILLS and block:
                out.append((skill, block))
    else:  # legacy single-skill shape
        block = (step_input.get("lessonAppendMarkdown") or "").strip()
        if block:
            out.append(("tlf-generator", block))
    return out


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
        return

    run_id = (
        os.environ.get("RUN_ID")
        or step_input.get("runId")
        or step_input.get("processInstanceId")
        or ""
    )
    branch = f"skill-lesson/{run_id}" if run_id else "skill-lesson/adhoc"

    lessons = collect_lessons(step_input)
    if not step_input.get("hasLessons") or not lessons:
        skip(branch, "no-lessons")
        return

    pr_title = step_input.get("prTitle") or f"skill lessons from run {run_id}"
    pr_body = step_input.get("prBody") or "Auto-generated by the cdisc-case-3 self-learning loop."

    if CLONE_DIR.exists():
        shutil.rmtree(CLONE_DIR)
    CLONE_DIR.mkdir(parents=True)

    clone_url = f"https://x-access-token:{token}@github.com/{remote}.git"
    try:
        run(["git", "clone", "--depth", "1", clone_url, str(CLONE_DIR)])
    except subprocess.CalledProcessError as exc:
        fail(f"git clone failed: {exc.stderr.strip()[-400:]}")

    touched: list[str] = []
    rel_paths: list[str] = []
    for skill, block in lessons:
        rel = lessons_file_for(skill)
        if append_lesson(CLONE_DIR, rel, "\n" + block + "\n"):
            touched.append(skill)
            rel_paths.append(rel)

    if not touched:
        skip(branch, "lessons-already-present")
        return

    run(["git", "checkout", "-b", branch], cwd=CLONE_DIR)

    git_env = os.environ.copy()
    git_env["GIT_AUTHOR_NAME"] = COMMIT_AUTHOR_NAME
    git_env["GIT_AUTHOR_EMAIL"] = COMMIT_AUTHOR_EMAIL
    git_env["GIT_COMMITTER_NAME"] = COMMIT_AUTHOR_NAME
    git_env["GIT_COMMITTER_EMAIL"] = COMMIT_AUTHOR_EMAIL

    run(["git", "add", *rel_paths], cwd=CLONE_DIR, env=git_env)
    diff_check = run(["git", "diff", "--cached", "--quiet"], cwd=CLONE_DIR, check=False, env=git_env)
    if diff_check.returncode == 0:
        skip(branch, "no-staged-changes")
        return

    run(["git", "commit", "-m", f"skill lessons from run {run_id} ({', '.join(touched)})"], cwd=CLONE_DIR, env=git_env)
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

    write_result({"prCreated": True, "prUrl": pr_url, "branch": branch, "skills": touched, "reason": None})
    print(f"open_skill_pr: opened {pr_url} for {touched}", file=sys.stderr)


if __name__ == "__main__":
    main()
