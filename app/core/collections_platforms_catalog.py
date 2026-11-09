"""Subscription platform families, matched against regional TMDb providers."""
PLATFORMS={
    'netflix':{'name':'Netflix','ids':[8,1796],'aliases':['Netflix','Netflix Standard with Ads']},
    'prime':{'name':'Prime Video','ids':[119,2100],'aliases':['Amazon Prime Video','Amazon Prime Video with Ads','Prime Video']},
    'disney':{'name':'Disney+','ids':[337],'aliases':['Disney Plus','Disney+']},
    'apple':{'name':'Apple TV+','ids':[350],'aliases':['Apple TV','Apple TV+','Apple TV Plus','Apple TV Amazon Channel']},
    'max':{'name':'Max','ids':[1899,384],'aliases':['Max','HBO Max','HBO Max Amazon Channel','Max Amazon Channel']},
    'paramount':{'name':'Paramount+','ids':[531,582],'aliases':['Paramount Plus','Paramount+','Paramount+ Amazon Channel','Paramount Plus Apple TV Channel','Paramount+ with Showtime']},
    'canal':{'name':'Canal+','ids':[381],'aliases':['Canal+','Canal Plus']},
}


def platform_collection_title(key,country,language='en'):
    from core.collections_repository import STREAMING_COUNTRY_NAMES
    region=STREAMING_COUNTRY_NAMES.get(language,STREAMING_COUNTRY_NAMES['en']).get(country,country)
    return PLATFORMS[key]['name']+' · '+region
