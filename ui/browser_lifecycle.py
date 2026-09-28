"""Explicit browser departures stop the CLI server after a reload grace period.

No heartbeat timeout: background tabs and sleeping laptops must not lose data.
Only top-level pages participate; comparison iframes never own the server.
"""
import threading


class BrowserLifecycle:
    def __init__(self, shutdown, grace=10):
        self.shutdown = shutdown
        self.grace = grace
        self.lock = threading.RLock()
        self.clients = set()
        self.departed = set()
        self.timer = None
        self.stopping = False

    def update(self, client, leaving=False):
        if not isinstance(client, str) or not 1 <= len(client) <= 100:
            raise ValueError('Invalid browser session identifier.')
        with self.lock:
            if self.stopping:
                return
            if leaving:
                self.departed.add(client)
                self.clients.discard(client)
            elif client not in self.departed:
                self.clients.add(client)
            if self.timer:
                self.timer.cancel()
                self.timer = None
            if not self.clients and self.departed:
                self.timer = threading.Timer(self.grace, self.finish_if_empty)
                self.timer.daemon = True
                self.timer.start()

    def finish_if_empty(self):
        with self.lock:
            if self.clients or self.stopping:
                return
            self.stopping = True
        self.shutdown()

    def close(self):
        with self.lock:
            self.stopping = True
            if self.timer:
                self.timer.cancel()
