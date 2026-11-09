"""Curated award identities and principal-winning-category filters."""
import json
import re
from pathlib import Path

CATALOG=json.loads((Path(__file__).resolve().parents[1]/'data'/'awards_sources.json').read_text(encoding='utf-8'))
AWARDS=CATALOG['awards']


def award_period(value):
    value=str(value or 'latest')
    if value not in ('latest','all') and not (re.fullmatch(r'[0-9]{4}',value) and 1900<=int(value)<=2100):
        raise ValueError('collections.awards_invalid_period')
    return value


def awards_collection_name(award, period='latest', language='fr'):
    if not isinstance(award,str) or award not in AWARDS:raise ValueError('collections.awards_invalid_award')
    period=award_period(period)
    labels={'fr':('Lauréats','Dernière édition','Toutes les années'),'en':('Winners','Latest edition','All years'),
            'de':('Preisträger','Letzte Ausgabe','Alle Jahre'),'es':('Ganadores','Última edición','Todos los años'),
            'it':('Vincitori','Ultima edizione','Tutti gli anni')}
    label,latest,all_years=labels.get(language,labels['fr'])
    return AWARDS[award]['name']+' · '+label+' · '+(latest if period=='latest' else all_years if period=='all' else period)


def awards_options():
    return [{'id':key,'label':row['name'],'media_types':row['media_types']} for key,row in AWARDS.items()]
