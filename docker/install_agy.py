"""Install the pinned official artifact, checking its hash before unpacking."""

import hashlib
import json
import platform
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

arch = {"x86_64": "amd64", "aarch64": "arm64"}[platform.machine()]
release = json.loads(Path("/tmp/agy-release.json").read_text())["linux_" + arch]
with tempfile.TemporaryDirectory() as folder:
    archive = Path(folder) / "agy.tar.gz"
    digest = hashlib.sha512()
    with urllib.request.urlopen(release["url"], timeout=120) as response, archive.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != release["sha512"]:
        raise ValueError("Antigravity artifact checksum mismatch")
    with tarfile.open(archive) as package:
        binary = next(item for item in package if item.isfile() and Path(item.name).name == "antigravity")
        with package.extractfile(binary) as source, Path("/usr/local/bin/agy").open("wb") as output:
            shutil.copyfileobj(source, output)
    Path("/usr/local/bin/agy").chmod(0o755)
