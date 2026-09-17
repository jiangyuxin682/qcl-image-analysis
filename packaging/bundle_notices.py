"""Preserve installed third-party notices and the bundled FFmpeg build identity."""
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys

import imageio_ffmpeg


def main():
    destination = Path(sys.argv[1]) / "THIRD_PARTY"
    destination.mkdir(parents=True, exist_ok=True)
    versions = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name", "unknown")
        versions[name] = dist.version
        for file in dist.files or []:
            if any(word in file.name.lower() for word in ("license", "copying", "notice")):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    relative = Path(*[part for part in file.parts if part not in ("..", ".")])
                    target = destination / name / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    (destination / "versions.json").write_text(json.dumps(versions, indent=2), encoding="utf-8")
    executable = imageio_ffmpeg.get_ffmpeg_exe()
    for option in ("-version", "-L"):
        result = subprocess.run([executable, option], capture_output=True, check=True)
        (destination / ("FFMPEG_VERSION.txt" if option == "-version" else "FFMPEG_LICENSE.txt")).write_bytes(result.stdout + result.stderr)
    (destination / "FFMPEG_SOURCE.txt").write_text(
        "FFmpeg executable distributed by imageio-ffmpeg 0.6.0.\n"
        "Binary provenance and build scripts: https://github.com/imageio/imageio-ffmpeg/tree/v0.6.0\n"
        "Upstream source releases: https://ffmpeg.org/releases/\n"
        "See FFMPEG_VERSION.txt for the included build version and configuration.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
