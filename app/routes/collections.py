from core.collections_franchise_lists import definitions as franchise_list_definitions
from core.collections_page_data import load_collections_page_data
from core.auth_principal import admin_required
from core.collections_repository import hidden_gems_name
from core.collections_platforms_catalog import PLATFORMS
from core.collections_diagnostics import normalize_collection_result, collection_count_snapshots
from core.collections_awards_catalog import awards_options, awards_collection_name, AWARDS
from core.collections_repository import family_collection_name
from core.collections_repository import top_country_name
from core.collections_tmdb_catalog import tmdb_charts
"""Read-only workspace for designing collections before their engines are added."""
import json
import os
from db_manager import isolated_read_operation
from flask import render_template, request, jsonify, Response, abort

from core.collections_repository import recently_added_name, kids_collection_name
from core.collections_anime_catalog import anime_charts
from core.collections_imdb_catalog import imdb_charts, CHART_LABELS
from core.collections_streaming_options import EXTRA_COUNTRIES, CONTENT_LANGUAGES
from core.collection_catalog import FUTURE_MODELS, collection_catalog
from core.server_page_queries import LIBRARY_TYPE_SQL
from web.helpers import get_db
from core.collections_repository import list_instances, load_instance, save_instance, request_run, collection_settings, save_collection_settings, group_members, stop_collection, recover_stale_collection_runs, stamp, seasonal_collection_name, global_timezone, utcnow, recent_collection_name, WORLDWIDE_TITLES, STREAMING_REGIONS, worldwide_collection_name, STREAMING_COUNTRY_NAMES, streaming_collection_name
from core.collections_people import list_people, members, exclude_person, add_manual_person
from core.collections_memoria_source import MemoriaSource
from core.collection_inventory import inventory_status
from core.collections_seasonal_calendar import EVENT_IDS, seasonal_calendar
from dateutil.tz import gettz
from core.error_reporting import log_handled_failure
from logging_utils import get_logger, is_debug_mode_enabled
from secret_store import SecretDecryptionError, decrypt_secret


def collection_request_payload():
    payload=request.get_json(silent=True)
    if payload is None:return {}
    if not isinstance(payload,dict):raise ValueError('collections.invalid_configuration')
    return payload


def publication_snapshot(db, instance_id, person_key):
    snapshot=db.query_one("""SELECT p.run_id,p.publication_json FROM collection_publication_snapshots p
        JOIN collection_objects o ON o.id=p.object_id
        WHERE o.instance_id=? AND o.person_key=? AND o.remote_id IS NOT NULL AND o.state!='deleted'""",
        (instance_id,person_key))
    if snapshot:
        return snapshot['run_id'],json.loads(snapshot['publication_json'])
    compacted=db.query_one("SELECT history_compacted FROM collection_instances WHERE id=?",(instance_id,))
    if compacted and compacted['history_compacted']:
        return None,None
    return _legacy_publication_snapshot(db, instance_id, person_key)


def _legacy_publication_snapshot(db, instance_id, person_key):
    # Select only the latest successful publication for this object. Do not
    # replay all historical library-sized snapshots on every browser poll.
    row=db.query_one("""SELECT r.id,p.value FROM collection_runs r,
        json_each(r.result_json,'$.people') p
        WHERE r.instance_id=? AND r.kind!='preview'
          AND json_extract(p.value,'$.person_key')=?
          AND json_extract(p.value,'$.published')=1
        ORDER BY r.id DESC LIMIT 1""",(instance_id,person_key))
    return (row['id'],json.loads(row['value'])) if row else (None,None)


@isolated_read_operation
def load_collections_poll_data(db, compact=False):
    runs = []
    for row in db.query('''SELECT r.id,r.instance_id,r.kind,r.state,r.started_at,r.finished_at,r.error_type,
            '''+("json_remove(r.result_json,'$.people')" if compact else 'r.result_json')+''' AS result_json,
            i.name, i.model, COALESCE(i.group_id,i.id) AS group_id, l.name AS library_name FROM collection_runs r JOIN collection_instances i ON i.id=r.instance_id
            JOIN libraries l ON l.id=i.library_id
            ORDER BY r.id DESC LIMIT 100'''):
        row = dict(row)
        row['result'] = normalize_collection_result(json.loads(row.pop('result_json')),row['model'])
        runs.append(row)
    task = db.query_one("SELECT * FROM tasks WHERE name='refresh_collection_inventory'")
    objects = []
    source_objects = db.query('''SELECT o.*,i.model,i.name AS configuration_name,COALESCE(i.group_id,i.id) AS group_id,
            l.name AS library_name,p.name,p.data_json,p.expires_at,
            i.history_compacted AS publication_history_compacted,
            snapshot.object_id AS publication_object_id,
            snapshot.run_id AS publication_snapshot_run_id,
            snapshot.publication_json AS publication_snapshot_json FROM collection_objects o
            JOIN collection_instances i ON i.id=o.instance_id JOIN libraries l ON l.id=i.library_id
            LEFT JOIN collection_people p ON p.instance_id=o.instance_id AND p.person_key=o.person_key
            LEFT JOIN collection_publication_snapshots snapshot ON snapshot.object_id=o.id
            WHERE o.remote_id IS NOT NULL AND o.state!='deleted' ORDER BY i.created_at,o.title,l.id''')
    for row in source_objects:
        item = dict(row)
        item['profile_path'] = json.loads(item.pop('data_json') or '{}').get('profile_path')
        snapshot_id = item.pop('publication_object_id')
        snapshot_run_id = item.pop('publication_snapshot_run_id')
        snapshot_json = item.pop('publication_snapshot_json')
        history_compacted = item.pop('publication_history_compacted')
        if snapshot_id is not None:
            publication_id, publication = snapshot_run_id, json.loads(snapshot_json)
        elif history_compacted:
            publication_id, publication = None, None
        else:
            publication_id, publication = _legacy_publication_snapshot(db,item['instance_id'],item['person_key'])
        item['publication_run_id']=publication_id
        if compact and publication:
            media=publication.get('media') or [{'title':title,'present':True,'arr_status':'not_needed'} for title in publication.get('selected',[])]
            publication={**publication,'media':media[:5],
                'present':publication.get('present',sum(row.get('present') is True or row.get('arr_status')=='not_needed' for row in media)),
                'missing':publication.get('missing',sum(row.get('present') is not True and row.get('arr_status')!='not_needed' for row in media)),
                'arr_requests':sum(row.get('arr_status')=='added' for row in media),
                'media_total':len(media),'media_compact':len(media)>5}
            publication.pop('selected',None)
        item['publication'] = publication
        objects.append(item)
    return dict(ok=True,instances=list_instances(db),counts=collection_count_snapshots(db),settings=collection_settings(db),runs=runs,objects=objects,
        inventory={'libraries':inventory_status(db),'task':{key:dict(task).get(key) for key in ('status','next_run')} if task else {},
            'last_run':dict(row) if (row:=db.query_one('SELECT * FROM collection_inventory_runs ORDER BY id DESC LIMIT 1')) else None})


def register(app):
    @app.get("/collections")
    def collections_page():
        db = get_db()
        page_data = load_collections_page_data(db)
        return render_template(
            "collections/collections.html", active_page="collections",
            hidden_gems_names={language:hidden_gems_name(language) for language in CHART_LABELS},
            family_names={language:family_collection_name(language) for language in CHART_LABELS},
            top_country_names={language:{chart:{country:top_country_name(country,language,chart) for country in countries} for chart in ('top','popular')} for language,countries in STREAMING_COUNTRY_NAMES.items()},
            recently_added_names={language:recently_added_name('recently_added',language) for language in CHART_LABELS},
            kids_names={language:{chart:{country:kids_collection_name(country,language,chart) for country in countries} for chart in ('top','latest')} for language,countries in STREAMING_COUNTRY_NAMES.items()},
            franchise_lists=franchise_list_definitions(db),
            awards_options=awards_options(), award_years=list(range(utcnow().year,1899,-1)),
            awards_names={language:{award:awards_collection_name(award,'latest',language).split(' · ')[0] for award in AWARDS} for language in CHART_LABELS},
            tmdb_charts={language:tmdb_charts(language) for language in CHART_LABELS},
            anime_charts={language:anime_charts(language) for language in CHART_LABELS},
            imdb_charts={language:imdb_charts(language) for language in CHART_LABELS},
            streaming_countries=EXTRA_COUNTRIES, content_languages=CONTENT_LANGUAGES,
            platform_options={key:spec['name'] for key,spec in PLATFORMS.items()},
            catalog=collection_catalog(), future_models=FUTURE_MODELS, collection_debug=is_debug_mode_enabled(),
            libraries=page_data["libraries"], arr_servers=page_data["arr_servers"],
            worldwide_names=WORLDWIDE_TITLES, region_names={language:{region:worldwide_collection_name(region,language) for region in STREAMING_REGIONS} for language in WORLDWIDE_TITLES}, seasonal_events=EVENT_IDS,
            seasonal_names={language:{country:seasonal_collection_name(country,language) for country in countries} for language,countries in STREAMING_COUNTRY_NAMES.items()},
            recent_names={language:{country:recent_collection_name(country,language) for country in countries} for language,countries in STREAMING_COUNTRY_NAMES.items()},
            streaming_names={language:{country:streaming_collection_name(country,language) for country in countries} for language,countries in STREAMING_COUNTRY_NAMES.items()},
            instances=page_data["instances"], collection_settings=page_data["collection_settings"],
        )

    def failure(exc):
        if isinstance(exc,SecretDecryptionError):
            log_handled_failure('collections.secret_store',level='error')
            return jsonify(ok=False,error='collections.secret_store_unavailable'),500
        log_handled_failure('collections.admin_action')
        key = str(exc)
        if not key.startswith('collections.') or len(key)>100:
            key = 'collections.invalid_configuration'
        return jsonify(ok=False,error=key), 409 if key in ('collections.busy','collections.task_disabled') else 400

    from routes.collection_lists import register as register_lists
    register_lists(app, failure, collection_request_payload)

    @app.get('/api/collections/seasonal/calendar')
    def collections_seasonal_calendar_api():
        try:
            zone=global_timezone(get_db())
            today=utcnow().astimezone(gettz(zone)).date()
            country=str(request.args.get('country') or 'FR').upper()
            language=str(request.args.get('language') or 'fr')
            return jsonify(ok=True,timezone=zone,today=today.isoformat(),events=seasonal_calendar(country,language,today))
        except (ValueError,TypeError) as exc:
            return failure(exc)

    @app.get('/api/collections/platform-options')
    def collection_platform_options():
        from core.collections_streaming_source import COUNTRIES
        from core.collections_platforms import PlatformAvailabilitySource
        from secret_store import decrypt_secret
        country=str(request.args.get('country','FR')).upper()
        media_type=request.args.get('media_type','movie')
        if country not in COUNTRIES or media_type not in ('movie','tv','both'):
            return jsonify(ok=False,error='collections.invalid_country'),400
        db=get_db()
        settings=db.query_one('SELECT secret_tmdb FROM collection_settings WHERE id=1')
        key=decrypt_secret(settings['secret_tmdb']) if settings and settings['secret_tmdb'] else os.environ.get('TMDB_API_KEY')
        if not key:return jsonify(ok=False,error='collections.tmdb_key_required'),400
        source=PlatformAvailabilitySource(key,'en');source.db=db
        try:
            available={key:set() for key in PLATFORMS}
            for kind in ('movie','tv') if media_type=='both' else (media_type,):
                for platform,ids in source.provider_ids(country,kind,list(PLATFORMS)).items():
                    available[platform].update(ids)
            return jsonify(ok=True,platforms=[{'id':key,'name':spec['name'],'available':bool(available[key])} for key,spec in PLATFORMS.items()])
        except Exception:
            return jsonify(ok=False,error='collections.platforms_source_failed'),502
        finally:source.close()

    @app.get('/api/collections')
    def collections_list_api():
        db = get_db()
        recover_stale_collection_runs(db)
        compact=request.args.get('compact')=='1'
        return jsonify(load_collections_poll_data(db, compact))

    @app.get('/api/collections/objects/<object_id>/publication')
    def collections_publication_api(object_id):
        db=get_db()
        obj=db.query_one("SELECT instance_id,person_key FROM collection_objects WHERE id=? AND remote_id IS NOT NULL AND state!='deleted'",(object_id,))
        if not obj:abort(404)
        run_id,publication=publication_snapshot(db,obj['instance_id'],obj['person_key'])
        return jsonify(ok=True,run_id=run_id,publication=publication)

    @app.post('/api/collections/inventory/refresh')
    def collections_inventory_refresh_api():
        try:
            task = get_db().query_one("SELECT * FROM tasks WHERE name='refresh_collection_inventory'")
            if not task or not task['enabled']:
                raise ValueError('collections.task_disabled')
            if task['status'] not in ('running','queued') and not task['queued_count']:
                from tasks_engine import enqueue_task
                if not enqueue_task(task['id']): raise ValueError('collections.task_disabled')
            return jsonify(ok=True)
        except ValueError as exc:
            return failure(exc)

    def people_payload(db, group_id):
        rows = members(db,group_id)
        return {'people':list_people(db,group_id),
                'editable':not any(row['lease_until'] and row['lease_until']>stamp() for row in rows),
                'max_people':json.loads(rows[0]['config_json']).get('max_people',4),
                'min_popularity':json.loads(rows[0]['config_json']).get('min_popularity',25)}

    @app.get('/api/collections/portrait')
    def collections_portrait_api():
        from core.collections_portraits import portrait_path, fetch_portrait
        path = portrait_path(request.args.get('path'))
        if not path:
            abort(404)
        try:
            result = fetch_portrait(path)
        except Exception:
            log_handled_failure('collections.portrait')
            abort(502)
        if not result:
            abort(404)
        data,content_type = result
        return Response(data,mimetype=content_type,headers={'Cache-Control':'private, max-age=3600','X-Content-Type-Options':'nosniff'})

    def person_source(db, group_id):
        rows = members(db,group_id)
        config = json.loads(rows[0]['config_json'])
        shared = db.query_one('SELECT secret_tmdb FROM collection_settings WHERE id=1')
        key = decrypt_secret(shared['secret_tmdb']) if shared and shared['secret_tmdb'] else os.environ.get('TMDB_API_KEY')
        return MemoriaSource(key,config['language'])

    @app.post('/api/collections/<instance_id>/stop')
    def collections_stop_api(instance_id):
        try:
            stop_collection(get_db(),instance_id)
            get_logger('collections').info('Collection stop requested group=%s',instance_id)
            return jsonify(ok=True)
        except (ValueError,TypeError) as exc:
            return failure(exc)

    @app.get('/api/collections/<instance_id>/people')
    def collections_people_api(instance_id):
        try:
            recover_stale_collection_runs(get_db())
            return jsonify(ok=True,**people_payload(get_db(),instance_id))
        except (ValueError,TypeError) as exc:
            return failure(exc)

    @app.post('/api/collections/<instance_id>/people/search')
    def collections_people_search_api(instance_id):
        source = None
        try:
            payload = collection_request_payload()
            source = person_source(get_db(),instance_id)
            return jsonify(ok=True,people=source.search_people(payload.get('query')))
        except (ValueError,TypeError) as exc:
            return failure(exc)
        except Exception:
            log_handled_failure('collections.people_search',level='error')
            return jsonify(ok=False,error='collections.people_source_failed'),502
        finally:
            if source is not None:
                source.close()

    @app.post('/api/collections/<instance_id>/people')
    def collections_people_update_api(instance_id):
        source = None
        try:
            db = get_db()
            payload = collection_request_payload()
            tmdb_id = int(payload.get('tmdb_id') or 0)
            action = payload.get('action')
            if action=='add':
                source = person_source(db,instance_id)
                add_manual_person(db,instance_id,source.manual_person(tmdb_id))
            elif action in ('exclude','restore'):
                exclude_person(db,instance_id,tmdb_id,action=='exclude')
            else:
                raise ValueError('collections.invalid_configuration')
            get_logger('collections').info('Person selection changed group=%s tmdb_id=%s action=%s',instance_id,tmdb_id,action)
            warnings = []
            try:
                from tasks_engine import enqueue_task
                from core.collections_repository import wake_due_collections
                wake_due_collections(db,enqueue_task)
            except Exception:
                log_handled_failure('collections.people_schedule_pending',level='error')
                warnings.append('collections.saved_schedule_pending')
            return jsonify(ok=True,warnings=warnings,**people_payload(db,instance_id))
        except (ValueError,TypeError) as exc:
            return failure(exc)
        except Exception:
            log_handled_failure('collections.people_update',level='error')
            return jsonify(ok=False,error='collections.people_source_failed'),502
        finally:
            if source is not None:
                source.close()

    @app.post('/api/collections/settings/secret/<provider>')
    @admin_required
    def collections_reveal_secret(provider):
        secret_columns = {'tmdb': 'secret_tmdb', 'myanimelist': 'secret_myanimelist'}
        column = secret_columns.get(provider)
        if column is None:
            abort(404)
        try:
            row = get_db().query_one('SELECT secret_tmdb,secret_myanimelist FROM collection_settings WHERE id=1')
            stored = row[column] if row else None
            value = decrypt_secret(stored) if stored else os.environ.get('TMDB_API_KEY') if provider == 'tmdb' else None
            response = jsonify(ok=True, value=value or '')
        except SecretDecryptionError as exc:
            response, status = failure(exc)
            response.status_code = status
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/api/collections/settings')
    def collections_settings_api():
        try:
            settings = save_collection_settings(get_db(),request.get_json(silent=True))
            get_logger('collections').info('Shared collection settings saved')
            return jsonify(ok=True,settings=settings)
        except (ValueError,TypeError) as exc:
            return failure(exc)

    @app.post('/api/collections')
    @app.post('/api/collections/<instance_id>/save')
    def collections_save_api(instance_id=None):
        try:
            instance = save_instance(get_db(),request.get_json(silent=True),instance_id)
            get_logger('collections').info('Collection configuration saved instance=%s library=%s model=%s',instance['id'],instance['library_id'],instance['model'])
            from core.collections_repository import wake_due_collections
            from tasks_engine import enqueue_task
            warnings = []
            try:
                from core.collections_control import start_controls
                start_controls(get_db())
                wake_due_collections(get_db(),enqueue_task)
            except Exception:
                # The configuration is already committed. A scheduler outage
                # must not turn that successful save into a misleading failure.
                log_handled_failure('collections.saved_schedule_pending',level='error')
                warnings.append('collections.saved_schedule_pending')
            return jsonify(ok=True,instance=instance,warnings=warnings)
        except (ValueError,TypeError) as exc:
            return failure(exc)

    @app.post('/api/collections/<instance_id>/duplicate')
    def collections_duplicate_api(instance_id):
        from secret_store import decrypt_secret
        try:
            db = get_db()
            source = next(iter(group_members(db,instance_id)),None)
            payload = request.get_json(silent=True)
            if not source or not isinstance(payload,dict):
                raise ValueError('collections.not_found')
            if payload.get('model') != source['model']:
                raise ValueError('collections.duplicate_library_hint')
            instance = save_instance(db,payload)
            return jsonify(ok=True,instance=instance)
        except (ValueError,TypeError) as exc:
            return failure(exc)

    @app.post('/api/collections/<instance_id>/run')
    def collections_run_api(instance_id):
        from tasks_engine import enqueue_task
        try:
            db = get_db()
            settings = db.query_one('SELECT enable_cron_jobs FROM settings WHERE id=1')
            task = db.query_one("SELECT id,enabled FROM tasks WHERE name='run_collections'")
            if not task or not task['enabled'] or not settings or not settings['enable_cron_jobs']:
                raise ValueError('collections.task_disabled')
            payload = collection_request_payload()
            request_run(db,instance_id,payload.get('kind','sync'))
            from core.collections_control import start_controls
            start_controls(db)
            if not enqueue_task(int(task['id'])):
                # Persisted request remains visible and can be picked up after re-enabling cron.
                raise ValueError('collections.task_disabled')
            return jsonify(ok=True,queued=True),202
        except (ValueError,TypeError) as exc:
            return failure(exc)
