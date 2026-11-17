import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = b"RED" + b"ACTED"


def tracked_files():
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    for name in result.stdout.split(b"\0"):
        if name:
            yield name.decode("utf-8", errors="surrogateescape")


def test_no_redacted_placeholders_in_tracked_files():
    offenders = []
    for name in tracked_files():
        path = REPO_ROOT / name
        try:
            if PLACEHOLDER in path.read_bytes():
                offenders.append(name)
        except OSError:
            continue
    assert not offenders, f"Placeholder found in tracked files: {offenders}"
