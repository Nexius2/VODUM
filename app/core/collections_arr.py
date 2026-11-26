"""Use VODUM's saved library routes and ARR request configuration."""
import json
from datetime import timedelta

from core.collections_repository import stamp, utcnow
from core.library_request_routing import compatible_arr_type, route_matches_media
from core.portal_media_requests import api, arr_defaults, add_media, MediaRequestError
from core.server_cooldown import should_skip_unreachable_server


def failure_detail(exc, arr, credit, stage):
    server = getattr(arr,'server',None) or getattr(exc,'arr_server',{})
    server = server if isinstance(server,dict) else {}
    status = getattr(exc,'http_status',None)
    if not isinstance(status,int):
        status = getattr(getattr(exc,'response',None),'status_code',None)
    status = status if isinstance(status,int) else None
    code = str(exc)
    reason = {'portal_requests_add_failed':'arr_add_rejected','portal_requests_add_uncertain':'arr_add_uncertain',
              'portal_requests_unavailable':'arr_unavailable','portal_requests_not_configured':'arr_defaults_required',
              'collections.arr_defaults_required':'arr_defaults_required','collections.arr_route_required':'arr_route_required',
              'collections.arr_server_offline':'arr_server_offline',
              'collections.arr_invalid_response':'arr_invalid_response'}.get(code,'arr_internal_error')
    if stage=='identity':
        reason = 'arr_identity_failed'
    elif status in (401,403):
        reason = 'arr_auth_failed'
    fields = getattr(exc,'validation_fields',[])
    fields = fields if isinstance(fields,list) else []
    return {'tmdb_id':credit['id'],'title':credit.get('title') or credit.get('name') or str(credit['id']),
            'server_id':server.get('id'),'server_name':server.get('name') or '',
            'provider':server.get('type') or '', 'stage':stage if stage in ('identity','lookup','inventory','add','preflight') else 'lookup',
            'reason':reason,'severity':'warning' if reason=='arr_server_offline' else 'error','http_status':status,'fields':fields,
            'connection_error':getattr(exc,'connection_error',None),
            'retryable':status is None or status==429 or status>=500,'error_type':type(exc).__name__}


def log_arr_failure(instance, library, detail, exc):
    """Log actionable context; never serialize provider exception messages."""
    from logging_utils import get_logger
    reason = detail['reason']
    explanations = {'arr_auth_failed':'Authentification refusée : vérifier la clé API et les permissions',
        'arr_server_offline':'Serveur Radarr/Sonarr hors ligne : impossible d’ajouter les médias pour le moment',
        'arr_unavailable':'API ARR indisponible : vérifier la connexion et la réponse du serveur',
        'arr_defaults_required':'Profil qualité ou dossier racine manquant, invalide ou inaccessible',
        'arr_route_required':'Aucun routage ARR compatible avec la sélection',
        'arr_invalid_response':'Réponse ARR invalide', 'arr_add_rejected':'Ajout refusé par ARR',
        'arr_add_uncertain':'Réponse perdue après ajout : vérifier le résultat dans ARR'}
    connection = getattr(exc,'connection_error',None)
    connection = connection if connection in {'ConnectionError','Timeout','ConnectTimeout','ReadTimeout','SSLError','InvalidURL','JSONDecodeError'} else None
    endpoint = getattr(exc,'endpoint',None)
    endpoint = endpoint if endpoint in {'/api/v3/qualityprofile','/api/v3/rootfolder','/api/v3/movie','/api/v3/series','/api/v3/movie/lookup','/api/v3/series/lookup'} else None
    context = {'collection_id':instance['id'],'collection_name':instance.get('name'),
        'library_id':library['id'],'library_name':library.get('name'),
        'server_id':detail['server_id'],'server_name':detail['server_name'],
        'provider':detail['provider'],'stage':detail['stage'],'reason':reason,
        'http_status':detail['http_status'],'connection_error':connection,'endpoint':endpoint}
    logger = get_logger('operations')
    report = logger.warning if reason=='arr_server_offline' else logger.error
    report('Collection ARR : %s | %s',
        explanations.get(reason,'Échec du traitement ARR'),json.dumps(context,ensure_ascii=False))


class CollectionArr:
    def __init__(self, db, library, config, *, heartbeat=lambda:None):
        self.db, self.library, self.config = db, library, config
        self.heartbeat = heartbeat
        expected = compatible_arr_type(library['type'])
        routes = db.query("""SELECT r.arr_server_id FROM library_arr_routes r JOIN servers s ON s.id=r.arr_server_id
            WHERE r.library_id=? AND r.enabled=1 AND LOWER(TRIM(s.type))=? ORDER BY r.priority,r.arr_server_id""",(library['id'],expected))
        selected = config.get('arr_server') or (routes[0]['arr_server_id'] if routes else None)
        # A collection stays bound to this ARR. Connection failures propagate;
        # never try another library route or another ARR as a replacement.
        if selected not in {row['arr_server_id'] for row in routes}:
            raise ValueError('collections.arr_route_required')
        self.server = dict(db.query_one('SELECT * FROM servers WHERE id=?',(selected,)))
        if should_skip_unreachable_server(self.server):
            error = MediaRequestError('collections.arr_server_offline')
            error.arr_server = self.server
            raise error
        condition = db.query_one('SELECT conditions_json FROM library_arr_conditions WHERE library_id=? AND arr_server_id=?',(library['id'],selected))
        self.conditions = json.loads(condition['conditions_json']) if condition else {}
        self.kind = 'movie' if expected == 'radarr' else 'series'
        self.id_key = 'tmdbId' if self.kind == 'movie' else 'tvdbId'
        try:
            self._prepare()
        except Exception as exc:
            # __init__ did not return an adapter: retain the selected server
            # for the caller's diagnostic, including parallel defaults reads.
            exc.arr_server = self.server
            raise

    def _prepare(self):
        self.heartbeat()
        self.choices = arr_defaults(self.server)
        defaults = json.loads(self.server.get('settings_json') or '{}').get('media_requests') or {}
        profile = next((row for row in self.choices['profiles'] if row['id']==defaults.get('quality_profile_id')),None)
        root = next((row for row in self.choices['roots'] if row['id']==defaults.get('root_folder_id')),None)
        if profile is None and not defaults.get('quality_profile_id') and len(self.choices['profiles'])==1:
            profile = self.choices['profiles'][0]
        if root is None and not defaults.get('root_folder_id') and len(self.choices['roots'])==1:
            root = self.choices['roots'][0]
        if not profile or not root or not root.get('path') or root.get('accessible') is False:
            raise ValueError('collections.arr_defaults_required')
        existing = self.api('/api/v3/'+self.kind)
        if not isinstance(existing,list):
            raise RuntimeError('Invalid ARR inventory')
        self.existing = {str(row.get(self.id_key)) for row in existing}

    def api(self, path, **kwargs):
        self.heartbeat()
        return api(self.server,path,**kwargs)

    def submit(self, instance_id, external_id, *, preview=False):
        self.heartbeat()
        def allowed():
            row=self.db.query_one('SELECT enabled,retired,requested,config_json FROM collection_instances WHERE id=?',(instance_id,))
            return bool(row and row['enabled'] and not row['retired'] and row['requested'] not in ('cancel','cleanup','delete')
                and json.loads(row['config_json']).get('arr_enabled',False))
        if not allowed():return 'disabled'
        self.stage = 'lookup'
        external_id = int(external_id)
        previous = self.db.query_one(
            'SELECT state,updated_at FROM collection_arr_requests WHERE arr_server_id=? AND media_type=? AND external_id=?',
            (self.server['id'],self.kind,external_id))
        # Confirmation is durable: a removal in ARR must not cause collections
        # to undo that decision on their next daily run.
        if previous and previous['state']=='confirmed':
            return 'requested'
        if previous and previous['state']=='adding' and previous['updated_at']>stamp(utcnow()-timedelta(minutes=15)):
            return 'pending'
        if str(external_id) in self.existing:
            if not preview:
                self.db.execute("UPDATE collection_arr_requests SET state='confirmed',updated_at=? WHERE arr_server_id=? AND media_type=? AND external_id=?",
                    (stamp(),self.server['id'],self.kind,external_id))
            return 'known'
        term = ('tmdb:' if self.kind == 'movie' else 'tvdb:') + str(external_id)
        lookup = self.api('/api/v3/'+self.kind+'/lookup',params={'term':term})
        if not isinstance(lookup,list):
            raise ValueError('collections.arr_invalid_response')
        media = next((row for row in lookup if str(row.get(self.id_key))==str(external_id)),None)
        if media is None:
            return 'not_found'
        metadata = {'genres':media.get('genres',[]),'collections':
            [media['collection']['title']] if isinstance(media.get('collection'),dict) and media['collection'].get('title') else [],'resolution':''}
        if not route_matches_media(self.conditions,metadata):
            return 'excluded'
        if preview:
            return 'planned'
        self.heartbeat()
        now, stale = stamp(), stamp(utcnow()-timedelta(minutes=15))
        with self.db.transaction() as cur:
            claim = cur.execute('SELECT state,updated_at FROM collection_arr_requests WHERE arr_server_id=? AND media_type=? AND external_id=?',
                (self.server['id'],self.kind,external_id)).fetchone()
            if claim and claim['state']=='confirmed':
                return 'requested'
            if claim and claim['state']=='adding' and claim['updated_at']>stale:
                return 'pending'
            cur.execute("""INSERT INTO collection_arr_requests(arr_server_id,media_type,external_id,instance_id,state,updated_at)
                VALUES(?,?,?,?,'adding',?) ON CONFLICT(arr_server_id,media_type,external_id)
                DO UPDATE SET instance_id=excluded.instance_id,state='adding',updated_at=excluded.updated_at""",
                (self.server['id'],self.kind,external_id,instance_id,now))
        # A fresh request uses this run's inventory. Re-read the full catalog
        # only to reconcile a previous claim or an ambiguous/conflicting POST,
        # rather than downloading thousands of ARR entries for every new film.
        self.stage = 'inventory'
        try:
            current = self.api('/api/v3/'+self.kind) if claim else []
            if not isinstance(current,list):
                raise ValueError('collections.arr_invalid_response')
            if not any(str(row.get(self.id_key))==str(external_id) for row in current):
                self.stage = 'add'
                try:
                    self.heartbeat()
                    if not allowed():
                        self.db.execute("DELETE FROM collection_arr_requests WHERE arr_server_id=? AND media_type=? AND external_id=? AND instance_id=? AND state='adding'",
                            (self.server['id'],self.kind,external_id,instance_id))
                        return 'disabled'
                    add_media(self.server,media,self.kind,choices=self.choices)
                except MediaRequestError as exc:
                    # Another requester may have added the same title between
                    # the inventory read and POST. Confirm by stable ID only.
                    if getattr(exc,'http_status',None) in (400,409) or str(exc)=='portal_requests_add_uncertain':
                        try:
                            after = self.api('/api/v3/'+self.kind)
                        except MediaRequestError:
                            raise exc
                        if not isinstance(after,list) or not any(str(row.get(self.id_key))==str(external_id) for row in after):
                            raise exc
                    else:
                        raise
        except MediaRequestError as exc:
            if getattr(exc,'http_status',None) in (400,401,403,404,409,422):
                self.db.execute("DELETE FROM collection_arr_requests WHERE arr_server_id=? AND media_type=? AND external_id=? AND instance_id=? AND state='adding'",
                    (self.server['id'],self.kind,external_id,instance_id))
            raise
        self.db.execute("UPDATE collection_arr_requests SET state='confirmed',updated_at=? WHERE arr_server_id=? AND media_type=? AND external_id=?",
            (stamp(),self.server['id'],self.kind,external_id))
        self.existing.add(str(external_id))
        return 'added'
