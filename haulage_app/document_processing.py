"""Minimal parent-created environment for isolated document workers."""

import os


def worker_environment():
    """Keep Python's runtime paths without passing application configuration.

    Heroku's relocated, shared-library Python needs its configured PYTHONHOME
    and LD_LIBRARY_PATH even when the child is launched with sys.executable.
    These two runtime settings are the only inherited values; PYTHONPATH,
    database URLs, service credentials and the rest of the parent environment
    remain outside the worker.
    """
    environment = {
        "PATH": os.defpath,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    for name in ("PYTHONHOME", "LD_LIBRARY_PATH"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment
