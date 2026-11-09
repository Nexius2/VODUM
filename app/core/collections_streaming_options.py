"""Additional streaming markets and original content languages."""
# slug, Netflix country label, JustWatch locale, display name
EXTRA_COUNTRIES = {
    'IN': ('india','India','en_IN','India'),
    'JP': ('japan','Japan','ja_JP','Japan'),
    'KR': ('south-korea','South Korea','ko_KR','South Korea'),
    'TW': ('taiwan','Taiwan','zh_TW','Taiwan'),
    'HK': ('hong-kong','Hong Kong','zh_HK','Hong Kong'),
    'ID': ('indonesia','Indonesia','id_ID','Indonesia'),
    'TH': ('thailand','Thailand','th_TH','Thailand'),
    'PH': ('philippines','Philippines','en_PH','Philippines'),
    'MY': ('malaysia','Malaysia','en_MY','Malaysia'),
    'SG': ('singapore','Singapore','en_SG','Singapore'),
    'VN': ('vietnam','Vietnam','vi_VN','Vietnam'),
    'PK': ('pakistan','Pakistan','en_PK','Pakistan'),
    'TR': ('turkey','Turkey','tr_TR','Türkiye'),
    'AE': ('united-arab-emirates','United Arab Emirates','en_AE','United Arab Emirates'),
    'SA': ('saudi-arabia','Saudi Arabia','ar_SA','Saudi Arabia'),
    'IL': ('israel','Israel','he_IL','Israel'),
    'AU': ('australia','Australia','en_AU','Australia'),
    'NZ': ('new-zealand','New Zealand','en_NZ','New Zealand'),
    'BR': ('brazil','Brazil','pt_BR','Brazil'),
    'MX': ('mexico','Mexico','es_MX','Mexico'),
    'AR': ('argentina','Argentina','es_AR','Argentina'),
    'CL': ('chile','Chile','es_CL','Chile'),
    'CO': ('colombia','Colombia','es_CO','Colombia'),
    'PE': ('peru','Peru','es_PE','Peru'),
    'ZA': ('south-africa','South Africa','en_ZA','South Africa'),
    'EG': ('egypt','Egypt','ar_EG','Egypt'),
    'NG': ('nigeria','Nigeria','en_NG','Nigeria'),
    'KE': ('kenya','Kenya','en_KE','Kenya'),
    'PT': ('portugal','Portugal','pt_PT','Portugal'),
    'NL': ('netherlands','Netherlands','nl_NL','Netherlands'),
    'AT': ('austria','Austria','de_AT','Austria'),
    'IE': ('ireland','Ireland','en_IE','Ireland'),
    'PL': ('poland','Poland','pl_PL','Poland'),
    'CZ': ('czech-republic','Czech Republic','cs_CZ','Czechia'),
    'HU': ('hungary','Hungary','hu_HU','Hungary'),
    'RO': ('romania','Romania','ro_RO','Romania'),
    'GR': ('greece','Greece','el_GR','Greece'),
    'SE': ('sweden','Sweden','sv_SE','Sweden'),
    'NO': ('norway','Norway','no_NO','Norway'),
    'DK': ('denmark','Denmark','da_DK','Denmark'),
    'FI': ('finland','Finland','fi_FI','Finland'),
}
CONTENT_LANGUAGES = dict(pair.split(':',1) for pair in (
    'hi:Hindi|ta:Tamil|te:Telugu|ml:Malayalam|kn:Kannada|bn:Bengali|mr:Marathi|pa:Punjabi|gu:Gujarati|ur:Urdu|'
    'fr:Français|en:English|de:Deutsch|es:Español|it:Italiano|pt:Português|ar:Arabic|'
    'ja:Japanese|ko:Korean|zh:Chinese|id:Indonesian|th:Thai|vi:Vietnamese|tl:Tagalog|'
    'ms:Malay|tr:Turkish|fa:Persian|he:Hebrew|ru:Russian|uk:Ukrainian|pl:Polish|'
    'nl:Dutch|sv:Swedish|da:Danish|no:Norwegian|fi:Finnish|cs:Czech|hu:Hungarian|'
    'ro:Romanian|el:Greek|sw:Swahili|af:Afrikaans'
).split('|'))
