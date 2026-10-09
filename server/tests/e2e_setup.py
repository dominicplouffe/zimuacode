"""Creates the git remotes the end-to-end tests clone task workspaces from.

Usage: python -m tests.e2e_setup <dir>  →  <dir>/octo/shop.git with fake GitHub's main files.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from tests.fake_github import INITIAL


def main(root: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp)
        for path, content in INITIAL["main"].items():
            (src / path).parent.mkdir(parents=True, exist_ok=True)
            (src / path).write_bytes(content)

        def git(*args: str, cwd: Path = src) -> None:
            subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

        git("init", "-q", "-b", "main")
        git("add", ".")
        git("-c", "user.name=e2e", "-c", "user.email=e2e@test", "commit", "-qm", "init")
        bare = root / "octo" / "shop.git"
        bare.parent.mkdir(parents=True, exist_ok=True)
        git("clone", "-q", "--bare", str(src), str(bare), cwd=root)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
