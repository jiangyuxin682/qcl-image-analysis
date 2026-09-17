"""Desktop-specific paths and startup behavior, independent of the native GUI."""
import errno
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

from ui.desktop import create_server
from ui.video_export import find_ffmpeg


def test_desktop_uses_another_port_only_when_default_is_occupied():
    instance = object()
    with patch.object(ThreadingHTTPServer, "__new__", side_effect=[OSError(errno.EADDRINUSE, "busy"), instance]) as constructor:
        assert create_server() is instance
        assert constructor.call_args_list[0].args[1] == ("127.0.0.1", 8766)
        assert constructor.call_args_list[1].args[1] == ("127.0.0.1", 0)


def test_desktop_reports_non_port_errors():
    with patch.object(ThreadingHTTPServer, "__new__", side_effect=OSError(errno.EACCES, "denied")):
        with pytest.raises(OSError, match="denied"):
            create_server()


def test_frozen_ffmpeg_is_resolved_without_path(tmp_path, monkeypatch):
    import ui.video_export as module
    folder = tmp_path / "ffmpeg"
    folder.mkdir()
    executable = folder / "ffmpeg-win64.exe"
    executable.write_bytes(b"test")
    monkeypatch.setattr(module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(module.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    assert Path(find_ffmpeg()) == executable
