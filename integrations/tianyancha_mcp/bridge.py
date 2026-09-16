"""Single-account browser task queue shared by the panel and standalone MCP."""
import secrets
import threading
import time

class Bridge:
    def __init__(self, token, timeout=45):
        self.token = token
        self.timeout = timeout
        self.lock = threading.Lock()
        self.serial = threading.Lock()
        self.pending = None
        self.last_seen = 0

    def poll(self):
        with self.lock:
            self.last_seen = time.monotonic()
            p = self.pending
            if p and not p['claimed'] and time.monotonic() < p['deadline']:
                p['claimed'] = True
                return p['job']
            return None

    def complete(self, job_id, result):
        with self.lock:
            p = self.pending
            if not p or not p['claimed'] or p['event'].is_set() or p['job']['id'] != job_id or time.monotonic() >= p['deadline']:
                return False
            p['result'] = result
            p['event'].set()
            return True

    def query(self, operation, url, **args):
        if not self.serial.acquire(blocking=False):
            raise RuntimeError('BUSY: another browser query is running; retry after it finishes')
        try:
            if time.monotonic() - self.last_seen > 10:
                raise RuntimeError('BROWSER_DISCONNECTED: open the extension bridge page and connect')
            p = {'job': {'id': secrets.token_hex(16), 'operation': operation, 'url': url, **args},
                 'event': threading.Event(), 'claimed': False, 'deadline': time.monotonic() + self.timeout}
            with self.lock:
                self.pending = p
            if not p['event'].wait(self.timeout):
                raise RuntimeError('UPSTREAM_TIMEOUT: browser query timed out; check the working tab')
            result = p['result']
            if result.get('error'):
                raise RuntimeError(result['error'])
            source = result.get('source', {})
            if not isinstance(source, dict) or source.get('url') != url:
                raise RuntimeError('SOURCE_CHANGED: returned URL does not match requested page')
            return result
        finally:
            with self.lock:
                self.pending = None
            self.serial.release()
