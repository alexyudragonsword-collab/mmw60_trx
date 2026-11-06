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
