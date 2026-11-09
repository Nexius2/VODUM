# Adapted from the user-supplied Selection du moment engine; no configuration or credentials copied.
"""Cycle réutilisable, sans dépendance au planificateur."""
from datetime import datetime, timedelta, timezone
import json
import logging
from dateutil.tz import gettz
from core.collections_spotlight_rules import score, recent_movie_start, recent_movie_end
from core.collections_repository import CollectionRunCancelled
from core.collections_media import CollectionOwnershipError
from logging_utils import get_logger
from core.error_reporting import log_handled_failure

log = get_logger("collections.spotlight")


class Engine:
    def __init__(self, config, db, plex, discovery, dry=False):
        self.c, self.db, self.plex, self.discovery, self.dry = config, db, plex, discovery, dry
        self.report = {}
        self.progress = getattr(discovery,'progress',lambda *args,**kwargs:None)

    def enter(self, key, tmdb, title, entered, expires, origin, event=None):
        self.db.write('INSERT INTO entries(plex_id,tmdb_id,title,entered,expires,origin,checked,event) VALUES(?,?,?,?,?,?,?,?)',
                      (key, tmdb, title, entered, expires, origin, entered, event))

    def retire(self, key, now, reason):
        cooldown = (now + timedelta(days=self.c['exclusions']['manual_removal_cooldown_days'])).isoformat()
        self.db.write('UPDATE entries SET active=0,reason=?,removed=?,cooldown=?,checked=? WHERE plex_id=? AND active=1',
                      (reason, now.isoformat(), cooldown, now.isoformat(), key))

    def reconcile(self, members, now):
        for op in self.db.query("SELECT * FROM operations WHERE status='pending'"):
            if op['action'] == 'add' and op['plex_id'] in members:
                if not self.dry:
                    # Retry an insertion interrupted after membership but before ordering.
                    self.plex.move_to_front(members[op['plex_id']])
                if not self.db.query('SELECT id FROM entries WHERE plex_id=? AND active=1', (op['plex_id'],)):
                    self.enter(op['plex_id'], op['tmdb_id'], op['title'], op['entered'], op['expires'], 'automatic', op['event'])
            elif op['action'] == 'remove' and op['plex_id'] not in members:
                self.retire(op['plex_id'], now, 'limit' if op['event']=='limit' else 'expired')
            self.db.write("UPDATE operations SET status='reconciled' WHERE id=?", (op['id'],))

    def mutate(self, action, movie, now, event=None):
        entered = now.isoformat()
        # Calendar days in configured timezone, including daylight-saving transitions.
        expires = (now + timedelta(days=self.c['collection']['retention_days'])).isoformat()
        if self.dry:
            log.info('SIMULATION %s%s : %s', action, ' en tête' if action == 'add' else '', movie.label)
            if action == 'add':
                self.enter(movie.key, movie.tmdb, movie.title, entered, expires, 'automatic', event)
            else:
                self.retire(movie.key, now, 'limit' if event=='limit' else 'expired')
            return True
        operation = self.db.write('INSERT INTO operations(action,plex_id,tmdb_id,title,entered,expires,event) VALUES(?,?,?,?,?,?,?)',
            (action, movie.key, movie.tmdb, movie.title, entered, expires, event))
        try:
            getattr(self.plex, action)(movie)
            actual = self.plex.members()
            present = movie.key in {m.key for m in actual}
            if action=='add' and getattr(self.plex,'ordered',False) and (not actual or actual[0].key!=movie.key):
                raise RuntimeError('Placement en tête non confirmé')
            if present != (action == 'add'):
                raise RuntimeError('Modification non confirmée')
        except (CollectionRunCancelled, CollectionOwnershipError):
            raise
        except Exception:
            log_handled_failure('collections.spotlight.cycle')
            self.report['mutation_failures']=self.report.get('mutation_failures',0)+1
            log.error('Plex : %s non confirmé pour %s ; réconciliation au prochain cycle', action, movie.title)
            return False
        # A crash here leaves a pending operation with original dates.
        if action == 'add':
            self.enter(movie.key, movie.tmdb, movie.title, entered, expires, 'automatic', event)
        else:
            self.retire(movie.key, now, 'limit' if event=='limit' else 'expired')
        self.db.write("UPDATE operations SET status='confirmed' WHERE id=?", (operation,))
        log.info('%s %s', action.upper(), movie.label)
        return True

    def blocked(self, movie, event, now):
        # Apply history to both Plex keys and TMDB IDs (multiple editions).
        history = self.db.query('SELECT * FROM entries WHERE plex_id=? OR (tmdb_id IS NOT NULL AND tmdb_id=?)',
                                (movie.key, movie.tmdb))
        for row in history:
            if row['active']:
                return True
            if row['reason'] == 'manual' and row['cooldown'] and datetime.fromisoformat(row['cooldown']) > now:
                return True
            if row['reason'] == 'expired':
                # Only a strictly newer worldwide digital release, after removal, is a new event.
                boundary = datetime.fromisoformat(row['removed']).date().isoformat()
                if event <= boundary or (row['event'] and event <= row['event']):
                    return True
        return False

    def run(self, mode='all', now=None):
        now = (now or datetime.now(timezone.utc)).astimezone(gettz(self.c['scheduler']['timezone']))
        report = self.report
        report.update(cleanup='skipped',population='skipped',added=0,removed=0,dry_run=self.dry,
            candidates=0,rejected_score=0,rejected_date=0,rejected_audio=0,blocked=0,mutation_failures=0)
        run_id = self.db.write('INSERT INTO runs(started) VALUES(?)', (now.isoformat(),))
        try:
            self.progress('cleanup')
            members = {m.key: m for m in self.plex.members()}
            report['initial'] = len(members)
            self.reconcile(members, now)
            first = not self.db.query("SELECT value FROM meta WHERE key='initialized'")
            active = {r['plex_id']: r for r in self.db.query('SELECT * FROM entries WHERE active=1')}
            for key, row in active.items():
                if key not in members:
                    self.retire(key, now, 'manual')
                    log.info('Retrait externe détecté : %s', row['title'])
            for key, movie in members.items():
                if key not in active:
                    self.enter(key, movie.tmdb, movie.title, now.isoformat(),
                               (now + timedelta(days=self.c['collection']['retention_days'])).isoformat(),
                               'existing' if first else 'manual')
                else:
                    self.db.write('UPDATE entries SET checked=? WHERE id=?', (now.isoformat(), active[key]['id']))
            self.db.write("INSERT OR REPLACE INTO meta VALUES('initialized','1')")
            if mode != 'populate':
                report['cleanup'] = 'ok'
                for row in self.db.query('SELECT * FROM entries WHERE active=1'):
                    if datetime.fromisoformat(row['expires']) > now or row['plex_id'] not in members:
                        continue
                    try:
                        log.info('EXPIRE %s entrée=%s', row['title'], row['entered'])
                        if self.mutate('remove', members[row['plex_id']], now):
                            report['removed'] += 1
                            members.pop(row['plex_id'])
                        else:
                            report['cleanup'] = 'partial'
                    except (CollectionRunCancelled, CollectionOwnershipError):
                        raise
                    except Exception:
                        log_handled_failure('collections.spotlight.cycle')
                        report['cleanup'] = 'partial'
                        log.error('Nettoyage échoué pour %s', row['title'])
            limit = self.c['collection'].get('limit',0)
            if limit and len(members)>limit:
                for movie in list(members.values())[limit:]:
                    if self.mutate('remove',movie,now,'limit'):
                        members.pop(movie.key)
                        report['removed'] += 1
                    else:
                        report['cleanup'] = 'partial'
            # Persist cleanup before discovery starts.
            self.db.write('UPDATE runs SET cleanup=? WHERE id=?', (report['cleanup'], run_id))
            if mode != 'cleanup':
                report['population'] = 'ok'
                try:
                    library = {}
                    for movie in self.plex.library():
                        if movie.tmdb:
                            library.setdefault(movie.tmdb, []).append(movie)
                        else:
                            log.info('SKIP %s : identifiant TMDB absent ou ambigu', movie.title)
                    candidates = []
                    self.progress('discovery')
                    for candidate in self.discovery.discover(now, self.c):
                        try:
                            report['candidates'] += 1
                            value, reason, eligible = score(candidate, now, self.c)
                            if eligible:
                                candidates.append((value, reason, candidate))
                            else:
                                report['rejected_score'] += 1
                                log.info('REJECT %s [TMDB=%s ; numérique=%s] score=%.1f profil=%s',
                                         candidate['title'], candidate.get('initial_release', 'inconnue'),
                                         max(candidate['events']), value, reason)
                        except (CollectionRunCancelled, CollectionOwnershipError):
                            raise
                        except Exception:
                            log_handled_failure('collections.spotlight.cycle')
                            report['population'] = 'partial'
                            log.error('Scoring candidat invalide')
                    if getattr(self.discovery, 'partial', False):
                        report['population'] = 'partial'
                    self.progress('selection',candidates=report['candidates'],eligible=len(candidates))
                    for value, reason, candidate in sorted(candidates, key=lambda item: item[0], reverse=True):
                        if limit and len(members)>=limit:
                            break
                        matches = library.get(candidate['id'], [])
                        if not matches:
                            log.info('REJECT %s : absent de Plex', candidate['title'])
                            continue
                        french_matches = []
                        for match in sorted(matches, key=lambda item: item.key):
                            if match.release_date is None or not recent_movie_start(now.date()) <= match.release_date <= recent_movie_end(now.date()):
                                report['rejected_date'] += 1
                                log.info('REJECT %s : date Plex attendue entre %s et %s',
                                         match.label, recent_movie_start(now.date()), recent_movie_end(now.date()))
                                continue
                            try:
                                if self.plex.has_french_audio(match):
                                    french_matches.append(match)
                                    break
                            except (CollectionRunCancelled, CollectionOwnershipError):
                                raise
                            except Exception:
                                log_handled_failure('collections.spotlight.cycle')
                                report['population'] = 'partial'
                                log.error('Plex : vérification audio impossible pour %s', match.title)
                        if not french_matches:
                            report['rejected_audio'] += 1
                            log.info('REJECT %s : aucune édition Plex avec date récente et audio français vérifiés', candidate['title'])
                            continue
                        movie = french_matches[0]
                        event = max(candidate['events']).isoformat()
                        if self.blocked(movie, event, now):
                            report['blocked'] += 1
                            log.info('REJECT %s : présent, exclusion ou événement déjà traité', movie.label)
                            continue
                        try:
                            self.progress('publish',added=report['added'],selected=movie.tmdb)
                            log.info('SELECT %s [TMDB=%s ; numérique=%s] score=%.1f %s',
                                     movie.label, candidate.get('initial_release', 'inconnue'), event, value, reason)
                            if self.mutate('add', movie, now, event):
                                report['added'] += 1
                                members[movie.key] = movie
                            else:
                                report['population'] = 'partial'
                        except (CollectionRunCancelled, CollectionOwnershipError):
                            raise
                        except Exception:
                            log_handled_failure('collections.spotlight.cycle')
                            report['population'] = 'partial'
                            report['mutation_failures'] += 1
                            log.error('Ajout échoué : %s', movie.title)
                except (CollectionRunCancelled, CollectionOwnershipError):
                    raise
                except Exception:
                    log_handled_failure('collections.spotlight.cycle')
                    report['population'] = 'failed'
                    log.error('Peuplement échoué ; résultat nettoyage=%s', report['cleanup'])
            report['final'] = len(members)
        except (CollectionRunCancelled, CollectionOwnershipError):
            raise
        except Exception:
            log_handled_failure('collections.spotlight.cycle')
            report['cleanup'] = 'failed' if report['cleanup'] == 'skipped' and mode != 'populate' else report['cleanup']
            report['population'] = 'failed' if mode != 'cleanup' else 'skipped'
            log.error('Synchronisation Plex/SQLite échouée')
        finally:
            self.db.write('UPDATE runs SET finished=?,cleanup=?,population=?,summary=? WHERE id=?',
                (datetime.now(timezone.utc).isoformat(), report['cleanup'], report['population'], json.dumps(report), run_id))
            log.info('SUMMARY %s', json.dumps(report, ensure_ascii=False))
        return report
