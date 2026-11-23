"""Per-configuration journals for the Spotlight cycle, in VODUM's database."""
import re
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS collection_spotlight_meta (
 instance_id TEXT NOT NULL REFERENCES collection_instances(id) ON DELETE CASCADE,
 key TEXT NOT NULL, value TEXT, PRIMARY KEY(instance_id,key));
CREATE TABLE IF NOT EXISTS collection_spotlight_entries (
 id INTEGER PRIMARY KEY, instance_id TEXT NOT NULL REFERENCES collection_instances(id) ON DELETE CASCADE,
 plex_id TEXT NOT NULL, tmdb_id INTEGER, title TEXT NOT NULL, entered TEXT NOT NULL,
 expires TEXT NOT NULL, origin TEXT NOT NULL, checked TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1, reason TEXT, removed TEXT, cooldown TEXT, event TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS idx_spotlight_active
 ON collection_spotlight_entries(instance_id,plex_id) WHERE active=1;
CREATE TABLE IF NOT EXISTS collection_spotlight_operations (
 id INTEGER PRIMARY KEY, instance_id TEXT NOT NULL REFERENCES collection_instances(id) ON DELETE CASCADE,
 action TEXT NOT NULL, plex_id TEXT NOT NULL, tmdb_id INTEGER, title TEXT NOT NULL,
 entered TEXT NOT NULL, expires TEXT NOT NULL, event TEXT, status TEXT NOT NULL DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS collection_spotlight_runs (
 id INTEGER PRIMARY KEY, instance_id TEXT NOT NULL REFERENCES collection_instances(id) ON DELETE CASCADE,
 started TEXT, finished TEXT, cleanup TEXT, population TEXT, summary TEXT);
"""


class CycleStore:
    def __init__(self, db, instance_id, preview=False):
        self.db, self.instance_id = db, instance_id
        self.snapshot = None
        if preview:
            self.snapshot = sqlite3.connect(':memory:')
            self.snapshot.row_factory = sqlite3.Row
            self.snapshot.executescript(SCHEMA)
            for name in ('meta','entries','operations','runs'):
                table = 'collection_spotlight_'+name
                for row in db.query('SELECT * FROM '+table+' WHERE instance_id=?',(instance_id,)):
                    columns = list(dict(row))
                    self.snapshot.execute('INSERT INTO '+table+' ('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',tuple(row))
            self.snapshot.commit()

    def statement(self, sql, args):
        if sql == "INSERT OR REPLACE INTO meta VALUES('initialized','1')":
            return 'INSERT OR REPLACE INTO collection_spotlight_meta(instance_id,key,value) VALUES(?,?,?)',(self.instance_id,'initialized','1')
        sql = re.sub(r'\b(entries|operations|runs|meta)\b',r'collection_spotlight_\1',sql)
        if sql.lstrip().upper().startswith('INSERT'):
            sql = re.sub(r'(INTO collection_spotlight_\w+\()',r'\1instance_id,',sql,count=1)
            sql = re.sub(r'VALUES\(', 'VALUES(?,',sql,count=1,flags=re.I)
            return sql,(self.instance_id,*args)
        # Parenthesize existing OR conditions so another instance cannot leak in.
        if re.search(r'\bWHERE\b',sql,re.I):
            head,condition = re.split(r'\bWHERE\b',sql,maxsplit=1,flags=re.I)
            sql = head+' WHERE ('+condition+') AND instance_id=?'
        else:
            sql += ' WHERE instance_id=?'
        return sql,(*args,self.instance_id)

    def query(self, sql, args=()):
        sql,args = self.statement(sql,args)
        return self.snapshot.execute(sql,args).fetchall() if self.snapshot else self.db.query(sql,args)

    def write(self, sql, args=()):
        sql,args = self.statement(sql,args)
        if self.snapshot:
            with self.snapshot:
                return self.snapshot.execute(sql,args).lastrowid
        return self.db.execute(sql,args).lastrowid

    def close(self):
        if self.snapshot:
            self.snapshot.close()
