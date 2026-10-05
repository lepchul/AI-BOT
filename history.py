"""Durable per-chat history and bounded retrieval. No cross-chat identity guessing."""
import re
import time

class History:
    def __init__(self, db):
        self.db=db
        with db.tx() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS archive(chat INTEGER,mid INTEGER,uid INTEGER,name TEXT,text TEXT,at REAL,PRIMARY KEY(chat,mid));
            CREATE TABLE IF NOT EXISTS history_state(chat INTEGER PRIMARY KEY,cursor INTEGER DEFAULT 0,enabled INTEGER DEFAULT 1,epoch INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS history_notes(chat INTEGER,lo INTEGER,hi INTEGER,text TEXT,PRIMARY KEY(chat,lo,hi));
            CREATE TABLE IF NOT EXISTS history_people(chat INTEGER,uid INTEGER,name TEXT,username TEXT,seen REAL,PRIMARY KEY(chat,uid));
            ''')
    def ensure(self,chat,cursor=0):
        with self.db.tx() as c:c.execute('INSERT OR IGNORE INTO history_state(chat,cursor) VALUES(?,?)',(chat,cursor))
    def state(self,chat):
        with self.db.tx() as c:
            r=c.execute('SELECT * FROM history_state WHERE chat=?',(chat,)).fetchone()
            return dict(r) if r else None
    def set_enabled(self,chat,value):
        with self.db.tx() as c:c.execute('UPDATE history_state SET enabled=? WHERE chat=?',(int(value),chat))
    def restart(self,chat):
        with self.db.tx() as c:c.execute('UPDATE history_state SET cursor=0,enabled=1,epoch=epoch+1 WHERE chat=?',(chat,))
    def add(self,chat,mid,uid,name,text,at,username=''):
        with self.db.tx() as c:
            if c.execute('SELECT 1 FROM optout WHERE chat=? AND uid=?',(chat,uid)).fetchone():return
            c.execute('INSERT INTO archive VALUES(?,?,?,?,?,?) ON CONFLICT(chat,mid) DO UPDATE SET text=excluded.text,name=excluded.name',(chat,mid,uid,name[:80],text,at))
            c.execute('INSERT INTO history_people VALUES(?,?,?,?,?) ON CONFLICT(chat,uid) DO UPDATE SET name=excluded.name,username=excluded.username,seen=excluded.seen WHERE excluded.seen>=history_people.seen',(chat,uid,name[:80],username[:80],at))
    def checkpoint(self,chat,epoch,cursor,note,lo):
        with self.db.tx() as c:
            row=c.execute('SELECT epoch,enabled FROM history_state WHERE chat=?',(chat,)).fetchone()
            if not row or row[0]!=epoch or not row[1]:return False
            if note:c.execute('INSERT OR REPLACE INTO history_notes VALUES(?,?,?,?)',(chat,lo,cursor,note[:1800]))
            c.execute('UPDATE history_state SET cursor=? WHERE chat=?',(cursor,chat))
            return True
    def forget(self,chat,uid):
        with self.db.tx() as c:
            c.execute('DELETE FROM archive WHERE chat=? AND uid=?',(chat,uid))
            c.execute('DELETE FROM history_people WHERE chat=? AND uid=?',(chat,uid))
            # Summaries may indirectly contain the participant, discard all of them.
            c.execute('DELETE FROM history_notes WHERE chat=?',(chat,))
            c.execute('UPDATE history_state SET epoch=epoch+1 WHERE chat=?',(chat,))
    def clear(self,chat):
        with self.db.tx() as c:
            for table in ('archive','history_notes','history_people'):c.execute(f'DELETE FROM {table} WHERE chat=?',(chat,))
            c.execute('UPDATE history_state SET enabled=0,epoch=epoch+1 WHERE chat=?',(chat,))
    def retrieve(self,chat,query):
        words=list(dict.fromkeys(re.findall(r'[\w]{3,}',query.casefold())))[:8]
        with self.db.tx() as c:
            # SQL lower handles ASCII only; Python casefold below handles Cyrillic.
            notes=[dict(x) for x in c.execute('SELECT lo,hi,text FROM history_notes WHERE chat=? ORDER BY hi DESC LIMIT 2000',(chat,))]
            ranked=sorted(notes,key=lambda x:sum(w in x['text'].casefold() for w in words),reverse=True)[:6]
            # Scan incrementally, retain only top matches; bounded result sent to API.
            matches=[]
            for r in c.execute('SELECT mid,uid,name,text,at FROM archive WHERE chat=? ORDER BY mid DESC',(chat,)):
                score=sum(w in (r['name']+' '+r['text']).casefold() for w in words)
                if score:
                    matches.append((score,dict(r)))
                    matches.sort(key=lambda x:x[0],reverse=True)
                    del matches[8:]
            recent=[dict(x) for x in c.execute('SELECT mid,uid,name,text,at FROM archive WHERE chat=? ORDER BY mid DESC LIMIT 12',(chat,))][::-1]
            people=[dict(x) for x in c.execute('SELECT uid,name,username,seen FROM history_people WHERE chat=? ORDER BY seen DESC LIMIT 30',(chat,))]
        return {'notes':ranked,'matches':[x[1] for x in matches],'recent':recent,'observed_accounts':people}
    def status(self,chat):
        with self.db.tx() as c:
            count=c.execute('SELECT COUNT(*) FROM archive WHERE chat=?',(chat,)).fetchone()[0]
            notes=c.execute('SELECT COUNT(*) FROM history_notes WHERE chat=?',(chat,)).fetchone()[0]
        return f'Архив: {count} сообщений; заметок: {notes}; состояние: {self.state(chat)}'
