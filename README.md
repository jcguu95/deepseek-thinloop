# deepseek-thinloop

A **project-agnostic thin agent loop**: let a cheap model (DeepSeek) do the dirty
work while *you* stay the interface — write a sharp brief, read only a clean
`status.json`, nudge when it slacks, never wade through its chain-of-thought.

> Brief in → `status.json` out.

## Why

Cheap models can grind through real work, but they slack and they fake "done".
This loop boxes one into a sandbox, hands it tools to explore a repo, edit files,
and run build/tests on its own — then **auto-verifies and computes the red tests
*it* introduced**, turning a noisy agent into a clean pipe.

It was forged on a real project (a PDF reader with an SBCL backend + Qt frontend)
and then factored into a generic engine: **any project plugs in with a single
profile**.

## How it works

```
operator writes brief ─► drive.sh <profile> <brief> <workspace>
                            │  profile: sandbox image / preflight / verify / parser / baseline / rules
                            ▼
                    sandbox.sh ensure ─► persistent container (mounts workspace → /workspace)
                            ▼
                    loop.py (function-calling loop)
                       ├─ file tools (list/read/grep/str_replace/write) → run on the host workspace (fast, path-pinned)
                       ├─ run_command → docker exec into the sandbox (the project's real toolchain)
                       └─ wrap-up: run verify → parse → subtract baseline → status.json
                            ▼
operator reads only status.json (finished_reason / new_failures / files_changed / summary)
```

File ops go through the host (the workspace is a bind-mount); only build/tests go
through the container. The agent explores freely but is pinned inside the
workspace.

## Quickstart

```bash
# 1) give the agent a git-isolated workspace
git clone <repo> /path/to/clone && cd /path/to/clone && git checkout -b deepseek/<task>

# 2) write profiles/<name>.json (sandbox image, verify command, parser, rules file)
# 3) write a brief (the task + explicit acceptance criteria + boundaries)

# 4) run
bash drive.sh profiles/<name>.json /tmp/brief.md /path/to/clone

# slacking / unfinished → continue the same run with a nudge
bash drive.sh profiles/<name>.json /tmp/brief.md /path/to/clone --continue --nudge "fix X"
```

Parsers ship for `generic` (exit code), plus `pytest` / `jest` / `cargo` and more
— each reports `N passed, M failed` with named failures and baseline exclusion.

## The point

Tools handle *mechanical* correctness. **You handle *judgment* correctness** —
a sharp brief, restrained intervention (signal, not the diagnosed answer), running
the real path before you trust green, reviewing before you merge. That discipline
is the project's spine; see [`DISCIPLINE.md`](DISCIPLINE.md).
