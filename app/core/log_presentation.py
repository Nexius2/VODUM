"""Human-readable explanations without changing or guessing historical events."""
import json
import re


def explain_log(record):
    message=str(record.get('message') or '')
    level=str(record.get('level') or '').upper()
    if level not in {'WARNING','ERROR','CRITICAL'}:return None
    match=re.search(r'operation=([a-zA-Z0-9_.]+)',message)
    operation=match[1] if match else ''
    source=str(record.get('source') or '')
    if operation.startswith(('collections.visibility','collections.priority','collections.control')):kind='presentation'
    elif operation.startswith('collections.inventory') or 'collections.inventory_' in message:kind='inventory'
    elif 'Collection ARR' in message:kind='arr'
    elif operation.startswith('collections') or 'collection(s) failed' in message or 'Collection ' in message:kind='collection'
    elif 'tasks' in source or '[TASK ' in message:kind='task'
    elif 'backup' in operation+source:kind='backup'
    elif 'mail' in operation+source or 'communication' in operation+source:kind='communication'
    elif 'monitor' in operation+source:kind='monitoring'
    elif 'auth' in operation+source or 'security' in operation+source:kind='access'
    elif 'server' in operation+source or 'sync' in operation+source:kind='server'
    else:kind='application'
    cause='unknown'
    if re.search(r'ReadTimeout|ConnectTimeout|\bTimeout\b',message):cause='timeout'
    elif 'SSLError' in message:cause='tls'
    elif 'ConnectionError' in message:cause='connection'
    elif re.search(r'(?:http_status|status)["\s:=]+(?:401|403)\b',message):cause='permission'
    elif 'arr_add_uncertain' in message:cause='uncertain'
    elif 'attempts exhausted: 0/' in message:cause='no_retry'
    code=re.search(r'(?:cause=|"errors"\s*:\s*\[\s*"|"reason"\s*:\s*")(collections\.[a-z_]+)',message)
    context=[]
    start=message.find('context=')
    if start>=0:
        try:
            data,_=json.JSONDecoder().raw_decode(message[start+8:])
            for key in ('collection_name','library_name','server_name','object_title','instance_id','library_id','server_id','run_id'):
                if isinstance(data,dict) and isinstance(data.get(key),(str,int)):
                    context.append(('log_help.'+key,str(data[key])))
        except (ValueError,TypeError):pass
    if not context:
        for marker in ('details=',' | {'):
            pos=message.find(marker)
            if pos<0:continue
            text=message[pos+len(marker):] if marker=='details=' else message[pos+3:]
            try:data,_=json.JSONDecoder().raw_decode(text)
            except (ValueError,TypeError):continue
            if isinstance(data,dict):
                for key in ('collection_name','library_name','server_name','collection_id','library_id','server_id'):
                    if isinstance(data.get(key),(str,int)):
                        label='instance_id' if key=='collection_id' else key
                        context.append(('log_help.'+label,str(data[key])))
    named=re.search(r'Collection (.+?) finished instance=([^ ]+) library=([^ ]+) server=(.+?) run=(\d+)',message)
    if named and not context:
        context=[('log_help.collection_name',named[1]),('log_help.server_name',named[4]),('log_help.library_id',named[3]),('log_help.run_id',named[5])]
    if not context:
        for key in ('library_id','server_id','run_id'):
            value=re.search(r'\b'+key+r'=(\d+)',message)
            if value:context.append(('log_help.'+key,value[1]))
    if code and code[1]=='collections.execution_failed':code=None
    return {'title':'log_help.title_'+kind,'cause':'log_help.cause_'+cause,
            'action':'log_help.action_'+('arr' if cause=='uncertain' else 'network' if cause in {'timeout','tls','connection'} else kind),
            'code':code[1] if code else None,'context':context,'unidentified':kind in {'collection','presentation','inventory','arr'} and not context}
