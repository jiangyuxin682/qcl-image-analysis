"""Create a small source/build kit for transfer from macOS to a Windows builder."""
from pathlib import Path
import zipfile


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "dist" / "QCL-Processing-Windows-BuildKit.zip"
    output.parent.mkdir(exist_ok=True)
    paths = [root / name for name in ("README.md", "pyproject.toml", ".gitignore", "build_windows.bat")]
    for folder in ("src", "ui", "tests", "packaging", ".github"):
        paths.extend(p for p in (root / folder).rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}
                     and p.name != ".DS_Store")
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            archive.write(path, Path("QCL-Processing-BuildKit") / path.relative_to(root))
    print(output)


if __name__ == "__main__":
    main()
