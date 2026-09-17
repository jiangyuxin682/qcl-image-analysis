"""PyInstaller directory bundle. Build on Windows x64 with Python 3.12."""
from pathlib import Path
import imageio_ffmpeg
from PyInstaller.utils.hooks import collect_all

project = Path(SPECPATH).parent
sk_data, sk_binaries, sk_imports = collect_all(
    "skimage", filter_submodules=lambda name: ".tests" not in name
)

a = Analysis(
    [str(project / "ui" / "desktop.py")],
    pathex=[str(project), str(project / "src")],
    binaries=sk_binaries + [(imageio_ffmpeg.get_ffmpeg_exe(), "ffmpeg")],
    datas=sk_data + [(str(project / "ui" / "static_processing"), "ui/static_processing")],
    hiddenimports=sk_imports,
    hooksconfig={"matplotlib": {"backends": ["Agg"]}},
    excludes=["pytest", "IPython", "notebook"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="QCL Processing", console=False, debug=False, strip=False, upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="QCL Processing", strip=False, upx=False)
