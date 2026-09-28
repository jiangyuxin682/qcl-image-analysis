"""Closing tabs must not terminate another open workspace or a reload."""
import threading
from ui.browser_lifecycle import BrowserLifecycle


def test_last_close_stops_server():
    stopped = threading.Event()
    lifecycle = BrowserLifecycle(stopped.set, grace=.02)
    lifecycle.update('tab')
    lifecycle.update('tab', leaving=True)
    assert stopped.wait(1)
    assert lifecycle.stopping


def test_reload_and_other_tabs_keep_server_alive():
    stopped = threading.Event()
    lifecycle = BrowserLifecycle(stopped.set, grace=.02)
    lifecycle.update('one')
    lifecycle.update('two')
    lifecycle.update('one', leaving=True)
    assert not stopped.wait(.05)
    lifecycle.update('two', leaving=True)
    lifecycle.update('new-page')
    assert not stopped.wait(.05)
    lifecycle.close()


def test_delayed_poll_cannot_resurrect_departed_page():
    stopped = threading.Event()
    lifecycle = BrowserLifecycle(stopped.set, grace=.02)
    lifecycle.update('one', leaving=True)
    lifecycle.update('one')
    assert stopped.wait(1)


def test_no_browser_and_idle_tabs_do_not_time_out():
    stopped = threading.Event()
    lifecycle = BrowserLifecycle(stopped.set, grace=.02)
    assert not stopped.wait(.05)
    lifecycle.update('background-tab')
    assert not stopped.wait(.05)
    lifecycle.close()
