import sqlite3
import time
from contextlib import contextmanager
class Store:
    def __init__(self,path):
        self.path=str(path)
        with self.tx() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS messages(chat INTEGER,mid INTEGER,uid INTEGER,name TEXT,text TEXT,at REAL,PRIMARY KEY(chat,mid));
            CREATE TABLE IF NOT EXISTS memory(id INTEGER PRIMARY KEY,chat INTEGER,text TEXT);
            CREATE TABLE IF NOT EXISTS nicknames(chat INTEGER,uid INTEGER,name TEXT,PRIMARY KEY(chat,uid));
            CREATE TABLE IF NOT EXISTS state(chat INTEGER PRIMARY KEY,paused INTEGER DEFAULT 0,last_attempt REAL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS usage(day TEXT PRIMARY KEY,n INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS optout(chat INTEGER,uid INTEGER,PRIMARY KEY(chat,uid));''')
    @contextmanager
    def tx(self):
        c=sqlite3.connect(self.path,timeout=15);c.row_factory=sqlite3.Row
        try:
            c.execute('BEGIN IMMEDIATE');yield c;c.commit()
        except Exception:c.rollback();raise
        finally:c.close()
    def add(self,chat,mid,uid,name,text):
        with self.tx() as c:
            c.execute('INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?)',(chat,mid,uid,name[:80],text[:1200],time.time()))
            c.execute('DELETE FROM messages WHERE chat=? AND mid NOT IN (SELECT mid FROM messages WHERE chat=? ORDER BY at DESC,mid DESC LIMIT 500)',(chat,chat))
    def opted_out(self,chat,uid):
        with self.tx() as c:return bool(c.execute('SELECT 1 FROM optout WHERE chat=? AND uid=?',(chat,uid)).fetchone())
    def forget_user(self,chat,uid):
        with self.tx() as c:
            c.execute('INSERT OR IGNORE INTO optout VALUES(?,?)',(chat,uid))
            c.execute('DELETE FROM messages WHERE chat=? AND uid=?',(chat,uid))
            c.execute('DELETE FROM nicknames WHERE chat=? AND uid=?',(chat,uid))
    def resume_user(self,chat,uid):
        with self.tx() as c:c.execute('DELETE FROM optout WHERE chat=? AND uid=?',(chat,uid))
    def cleanup(self,days):
        with self.tx() as c:
            c.execute('DELETE FROM messages WHERE at<?',(time.time()-days*86400,))
    def snapshot(self,chat,count):
        with self.tx() as c:
            messages=[dict(x) for x in c.execute('SELECT * FROM messages WHERE chat=? ORDER BY at DESC,mid DESC LIMIT ?',(chat,count))][::-1]
            memories=[dict(x) for x in c.execute('SELECT id,text FROM memory WHERE chat=? ORDER BY id DESC LIMIT 30',(chat,))]
            names={str(x['uid']):x['name'] for x in c.execute('SELECT uid,name FROM nicknames WHERE chat=?',(chat,))}
        return {'messages':messages,'memories':memories,'nicknames':names}
    def paused(self,chat):
        with self.tx() as c:
            r=c.execute('SELECT paused FROM state WHERE chat=?',(chat,)).fetchone();return bool(r and r[0])
    def pause(self,chat,value):
        with self.tx() as c:c.execute('INSERT INTO state(chat,paused) VALUES(?,?) ON CONFLICT(chat) DO UPDATE SET paused=excluded.paused',(chat,int(value)))
    def reserve(self,chat,day,interval,limit,now=None):
        now=time.time() if now is None else now
        with self.tx() as c:
            c.execute('INSERT OR IGNORE INTO state(chat) VALUES(?)',(chat,))
            r=c.execute('SELECT * FROM state WHERE chat=?',(chat,)).fetchone()
            if r['paused'] or now-r['last_attempt']<interval:return False
            c.execute('INSERT OR IGNORE INTO usage(day) VALUES(?)',(day,))
            if c.execute('SELECT n FROM usage WHERE day=?',(day,)).fetchone()[0]>=limit:return False
            c.execute('UPDATE usage SET n=n+1 WHERE day=?',(day,));c.execute('UPDATE state SET last_attempt=? WHERE chat=?',(now,chat))
            return True
    def remember(self,chat,text):
        if not 1<=len(text)<=600:raise ValueError('Память: 1..600 символов')
        with self.tx() as c:
            if c.execute('SELECT COUNT(*) FROM memory WHERE chat=?',(chat,)).fetchone()[0]>=30:raise ValueError('Предел 30 воспоминаний. Удали старое.')
            return c.execute('INSERT INTO memory(chat,text) VALUES(?,?)',(chat,text)).lastrowid
    def delete_memory(self,chat,mid):
        with self.tx() as c:c.execute('DELETE FROM memory WHERE chat=? AND id=?',(chat,mid))
    def nickname(self,chat,uid,name):
        if not 1<=len(name)<=60:raise ValueError('Ник: 1..60 символов')
        if self.opted_out(chat,uid):raise ValueError('Участник отключил память')
        with self.tx() as c:c.execute('INSERT INTO nicknames VALUES(?,?,?) ON CONFLICT(chat,uid) DO UPDATE SET name=excluded.name',(chat,uid,name))
    def clear(self,chat):
        with self.tx() as c:
            for table in ('messages','memory','nicknames'):c.execute(f'DELETE FROM {table} WHERE chat=?',(chat,))
