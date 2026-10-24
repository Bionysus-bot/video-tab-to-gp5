"""One project writer across the legacy and versioned conversion entry points."""
import threading

_lock = threading.RLock()
_owners = {}


def acquire(project, owner='legacy'):
    with _lock:
        if project in _owners:
            return False
        _owners[project] = owner
        return True


def release(project):
    with _lock:
        _owners.pop(project, None)


def busy(project):
    with _lock:
        return project in _owners
