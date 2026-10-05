"""Process lock released automatically after normal exit or crash."""
import sqlite3
from contextlib import contextmanager
@contextmanager
def single_instance(path):
    c=sqlite3.connect(str(path),timeout=0)
    try:
        try:c.execute('BEGIN EXCLUSIVE')
        except sqlite3.OperationalError:raise ValueError('Аккаунт уже запущен в другой программе. Останови main.py/login.py.') from None
        yield
    finally:c.close()
