"""Iron rule 7: the fingerprint tool's comparison is exact and its record is reproducible."""
import fingerprint as fp           # tools/ is on sys.path (conftest)


def test_compare_lists_every_moved_or_missing_value():
    a = {"x": {"y": "1.0", "z": "2.0"}, "w": "3"}
    b = {"x": {"y": "1.0", "z": "2.5"}, "v": "4"}
    diffs = fp.compare(a, b)
    assert diffs == ["v: <absent> -> 4", "w: 3 -> <absent>", "x/z: 2.0 -> 2.5"]
    assert fp.compare(a, a) == []


def test_raised_entries_are_listed_and_compare_equal():
    a = {"p": {"error": "ValueError: x", "trace": "..."}}
    assert fp.raised(a) == ["p/error"]
    assert fp.compare(a, dict(a)) == []


def test_primitive_record_is_reproducible():
    one = fp.primitive_values()
    two = fp.primitive_values()
    assert one == two
    assert "bcc.viterbi.numpy" in one and "cfo.stf.k8" in one and "rapp.p1db" in one


def test_digest_handles_complex_arrays():
    import numpy as np
    assert fp.digest(np.array([1 + 2j])) != fp.digest(np.array([1 - 2j]))
    assert fp.digest(np.array([1.0, 2.0])) == fp.digest(np.array([1.0, 2.0]))


def _repo(tmp_path):
    import subprocess

    def git(*a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=tmp_path, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(msg, name="f"):
        (tmp_path / name).write_text(msg)
        git("add", name)
        git("commit", "-q", "-m", msg)
        return git("rev-parse", "HEAD")
    git("init", "-q", "-b", "main")
    return git, commit


def test_the_walk_reads_a_pull_requests_own_commits_not_githubs_merge_commit(tmp_path):
    """A pull request's CI job runs on GitHub's merge of the PR into its base.
    That commit's first parent is the base, so a first-parent walk of
    base..HEAD saw the merge commit alone and no marker, and PR #76 (the
    first PR whose fingerprint moved) failed with every moving commit
    marked.  The range of such a head is its second parent's history; a
    push's range is as before."""
    import fingerprint_walk as walk            # tools/ is on sys.path (conftest)
    git, commit = _repo(tmp_path)
    base = commit("base")
    git("checkout", "-q", "-b", "pr")
    c1 = commit("receiver change (numbers-move)")
    c2 = commit("documents")
    git("checkout", "-q", "main")
    git("merge", "-q", "--no-ff", "-m", "Merge pr into main", "pr")           # what refs/pull/N/merge is
    merge = git("rev-parse", "HEAD")
    assert walk.commits(base, merge, cwd=tmp_path) == [c1, c2]
    assert [walk.marked(c, cwd=tmp_path) for c in (c1, c2, merge)] == [True, False, False]
    assert walk.commits(base, c2, cwd=tmp_path) == [c1, c2]                        # a push of the branch
    # a merge that is not "the PR into this base" keeps the first-parent rule (a branch that merged main in)
    git("checkout", "-q", "pr")
    git("checkout", "-q", "-b", "other", base)
    o1 = commit("other work", "g")
    git("checkout", "-q", "pr")
    git("merge", "-q", "--no-ff", "-m", "Merge other into pr", "other")
    m2 = git("rev-parse", "HEAD")
    assert walk.commits(base, m2, cwd=tmp_path) == [c1, c2, m2] and o1 not in walk.commits(base, m2, cwd=tmp_path)
    # and the verdict: the moved range passes on the marked commit's walk, fails with no marker anywhere
    a, b = {"x": 1}, {"x": 2}
    ok, msgs = walk.settle(base, a, b, [], 12, recorder=lambda s, out: b, shas=[c1, c2],
                           is_marked=lambda s: walk.marked(s, cwd=tmp_path))
    assert ok and "marked: 1 values moved" in msgs[0]
    ok, msgs = walk.settle(base, a, b, [], 12, shas=[merge], is_marked=lambda s: walk.marked(s, cwd=tmp_path))
    assert not ok and "no commit in the range" in msgs[0]
    assert walk.settle(base, a, b, ["numbers-move"], 12, shas=[merge])[0]
