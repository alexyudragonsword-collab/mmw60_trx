"""Is this tree the release it says it is?  And the notes a release page carries.

    python tools/release_check.py check 0.3.0            # every place that states the version agrees
    python tools/release_check.py check 0.3.0 --dry-run  # the same, an existing tag is no problem
    python tools/release_check.py notes 0.3.0            # the release notes, from CHANGELOG.md

``.github/workflows/release.yml`` runs ``check`` before it builds anything and ``notes`` for the
release page.  A release is cut from a tree in which

* ``pyproject.toml``, ``mmw60.__version__`` and the APK's ``versionName`` all say the version;
* ``CHANGELOG.md`` has that version as its newest heading, with nothing left under 未发布;
* the shipped baseline was computed at that version (what a page shows as each result's origin);
* every accepted example output prints that version on its second line;
* the tag ``v<version>`` does not exist yet.

Each of these was done by hand for 0.3.0, and one of them (the examples' version line) was nearly
missed; this is the list, as code.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UNRELEASED = "## 未发布"
BASELINE = ("table", "calibration_be", "array", "ay")


def remote_tags(root: Path) -> set[str]:
    """Tag names on ``origin`` (empty when the remote cannot be asked: the caller decides)."""
    r = subprocess.run(["git", "-C", str(root), "ls-remote", "--tags", "origin"], capture_output=True, text=True,
                       timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"git ls-remote failed: {r.stderr.strip()}")
    return {line.split("refs/tags/", 1)[1].removesuffix("^{}")
            for line in r.stdout.splitlines() if "refs/tags/" in line}


def changelog_section(text: str, version: str) -> tuple[str, str, str]:
    """``(heading line, body of the version's section, what sits under 未发布)``; raises ValueError
    when the version is not the newest versioned heading."""
    lines = text.splitlines()
    heads = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    if not heads or lines[heads[0]].strip() != UNRELEASED:
        raise ValueError(f"CHANGELOG.md does not open with '{UNRELEASED}'")
    if len(heads) < 2 or not re.match(rf"## {re.escape(version)}(\s|$)", lines[heads[1]]):
        newest = lines[heads[1]] if len(heads) > 1 else "(none)"
        raise ValueError(f"the newest versioned heading of CHANGELOG.md is not {version}: {newest[:60]}")
    end = heads[2] if len(heads) > 2 else len(lines)
    unreleased = "\n".join(lines[heads[0] + 1:heads[1]]).strip()
    return lines[heads[1]], "\n".join(lines[heads[1] + 1:end]).strip(), unreleased


def problems(version: str, root: Path = REPO, dry_run: bool = False, tags: set[str] | None = None) -> list[str]:
    """Everything that stops this tree from being released as ``version`` (empty: go)."""
    out = []
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        return [f"'{version}' is not a version like 0.3.0"]

    def stated(rel: str, pattern: str, what: str):
        m = re.search(pattern, (root / rel).read_text(encoding="utf-8"), flags=re.M)
        if m is None:
            out.append(f"{rel}: no {what} found")
        elif m.group(1) != version:
            out.append(f"{rel}: {what} is {m.group(1)}, not {version}")

    stated("pyproject.toml", r'^version = "([^"]+)"', "version")
    stated("src/mmw60/__init__.py", r'^__version__ = "([^"]+)"', "__version__")
    stated("android/app/build.gradle.kts", r'^\s*versionName = "([^"]+)"', "versionName")
    try:
        _, _, unreleased = changelog_section((root / "CHANGELOG.md").read_text(encoding="utf-8"), version)
        if unreleased:
            out.append(f"CHANGELOG.md still has entries under 未发布 ({len(unreleased.splitlines())} lines): "
                       "they would ship unannounced; move them under the version")
    except ValueError as exc:
        out.append(str(exc))
    for job in BASELINE:
        path = root / "src/mmw60/data/gui/baseline" / f"{job}.json"
        was = json.loads(path.read_text(encoding="utf-8"))["provenance"].get("version") if path.is_file() else None
        if was != version:
            out.append(f"shipped baseline {job}.json was computed at {was}, not {version} "
                       "(python tools/gui_baseline.py build)")
    expected = sorted((root / "examples/expected").glob("*.txt"))
    if not expected:
        out.append("no accepted example outputs under examples/expected/")
    for path in expected:
        second = path.read_text(encoding="utf-8").splitlines()[1:2]
        if not second or not second[0].startswith(f"mmw60 {version};"):
            out.append(f"examples/expected/{path.name}: line 2 does not say 'mmw60 {version};'")
    if not dry_run:
        if f"v{version}" in (remote_tags(root) if tags is None else tags):
            out.append(f"the tag v{version} already exists on origin: this version was released")
    return out


def notes(version: str, root: Path = REPO) -> str:
    """The release page's text: the version's CHANGELOG heading and opening paragraph, the titles of
    its entries, and what the attached files are (and are not)."""
    head, body, _ = changelog_section((root / "CHANGELOG.md").read_text(encoding="utf-8"), version)
    intro = body.split("\n### ", 1)[0].strip()
    titles = [ln[4:].strip() for ln in body.splitlines() if ln.startswith("### ")]
    return "\n".join([
        f"# mmw60 {version}", "", head[3:].strip(), "", intro, "", "## 这一版里的条目（全文在 `CHANGELOG.md`）", "",
        *[f"- {t}" for t in titles], "", "## 附件", "",
        f"- `mmw60-{version}-py3-none-any.whl`、`mmw60-{version}.tar.gz`：`pip install` 用。"
        "发版工作流把 wheel 装进干净环境、在仓库之外跑过自检（`python -m mmw60.appbridge`）。",
        f"- `mmw60-{version}-debug.apk`：手机外壳，**调试签名**（不是发行签名，装不上应用商店的更新链），"
        "只在 x86_64 模拟器上跑过设备测试，真机与 arm64 上的数值没有验证（`ROADMAP.md` F）。",
        "", "引擎声明：线性化的时域基带引擎，杂散 / 互调结论不能由它背书。", ""])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("version")
    c.add_argument("--dry-run", action="store_true", help="rehearsal: an existing tag is not a problem")
    n = sub.add_parser("notes")
    n.add_argument("version")
    args = ap.parse_args(argv)
    if args.cmd == "notes":
        sys.stdout.write(notes(args.version))
        return 0
    found = problems(args.version, dry_run=args.dry_run)
    for p in found:
        print("PROBLEM:", p)
    print(f"release {args.version}: {'not releasable' if found else 'every statement of the version agrees'}"
          + (" (dry run: the tag was not looked up)" if args.dry_run else ""))
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
