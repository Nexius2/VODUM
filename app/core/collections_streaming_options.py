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

# Localized display names, also used in collection titles.
EXTRA_COUNTRY_NAMES = {'en': {code: row[3] for code, row in EXTRA_COUNTRIES.items()}, **{
    'fr': {'IN': 'Inde', 'JP': 'Japon', 'KR': 'Corée du Sud', 'TW': 'Taïwan', 'HK': 'Hong Kong', 'ID': 'Indonésie', 'TH': 'Thaïlande', 'PH': 'Philippines', 'MY': 'Malaisie', 'SG': 'Singapour', 'VN': 'Viêt Nam', 'PK': 'Pakistan', 'TR': 'Turquie', 'AE': 'Émirats arabes unis', 'SA': 'Arabie saoudite', 'IL': 'Israël', 'AU': 'Australie', 'NZ': 'Nouvelle-Zélande', 'BR': 'Brésil', 'MX': 'Mexique', 'AR': 'Argentine', 'CL': 'Chili', 'CO': 'Colombie', 'PE': 'Pérou', 'ZA': 'Afrique du Sud', 'EG': 'Égypte', 'NG': 'Nigeria', 'KE': 'Kenya', 'PT': 'Portugal', 'NL': 'Pays-Bas', 'AT': 'Autriche', 'IE': 'Irlande', 'PL': 'Pologne', 'CZ': 'Tchéquie', 'HU': 'Hongrie', 'RO': 'Roumanie', 'GR': 'Grèce', 'SE': 'Suède', 'NO': 'Norvège', 'DK': 'Danemark', 'FI': 'Finlande'},
    'de': {'IN': 'Indien', 'JP': 'Japan', 'KR': 'Südkorea', 'TW': 'Taiwan', 'HK': 'Hongkong', 'ID': 'Indonesien', 'TH': 'Thailand', 'PH': 'Philippinen', 'MY': 'Malaysia', 'SG': 'Singapur', 'VN': 'Vietnam', 'PK': 'Pakistan', 'TR': 'Türkei', 'AE': 'Vereinigte Arabische Emirate', 'SA': 'Saudi-Arabien', 'IL': 'Israel', 'AU': 'Australien', 'NZ': 'Neuseeland', 'BR': 'Brasilien', 'MX': 'Mexiko', 'AR': 'Argentinien', 'CL': 'Chile', 'CO': 'Kolumbien', 'PE': 'Peru', 'ZA': 'Südafrika', 'EG': 'Ägypten', 'NG': 'Nigeria', 'KE': 'Kenia', 'PT': 'Portugal', 'NL': 'Niederlande', 'AT': 'Österreich', 'IE': 'Irland', 'PL': 'Polen', 'CZ': 'Tschechien', 'HU': 'Ungarn', 'RO': 'Rumänien', 'GR': 'Griechenland', 'SE': 'Schweden', 'NO': 'Norwegen', 'DK': 'Dänemark', 'FI': 'Finnland'},
    'es': {'IN': 'India', 'JP': 'Japón', 'KR': 'Corea del Sur', 'TW': 'Taiwán', 'HK': 'Hong Kong', 'ID': 'Indonesia', 'TH': 'Tailandia', 'PH': 'Filipinas', 'MY': 'Malasia', 'SG': 'Singapur', 'VN': 'Vietnam', 'PK': 'Pakistán', 'TR': 'Turquía', 'AE': 'Emiratos Árabes Unidos', 'SA': 'Arabia Saudí', 'IL': 'Israel', 'AU': 'Australia', 'NZ': 'Nueva Zelanda', 'BR': 'Brasil', 'MX': 'México', 'AR': 'Argentina', 'CL': 'Chile', 'CO': 'Colombia', 'PE': 'Perú', 'ZA': 'Sudáfrica', 'EG': 'Egipto', 'NG': 'Nigeria', 'KE': 'Kenia', 'PT': 'Portugal', 'NL': 'Países Bajos', 'AT': 'Austria', 'IE': 'Irlanda', 'PL': 'Polonia', 'CZ': 'Chequia', 'HU': 'Hungría', 'RO': 'Rumanía', 'GR': 'Grecia', 'SE': 'Suecia', 'NO': 'Noruega', 'DK': 'Dinamarca', 'FI': 'Finlandia'},
    'it': {'IN': 'India', 'JP': 'Giappone', 'KR': 'Corea del Sud', 'TW': 'Taiwan', 'HK': 'Hong Kong', 'ID': 'Indonesia', 'TH': 'Thailandia', 'PH': 'Filippine', 'MY': 'Malaysia', 'SG': 'Singapore', 'VN': 'Vietnam', 'PK': 'Pakistan', 'TR': 'Turchia', 'AE': 'Emirati Arabi Uniti', 'SA': 'Arabia Saudita', 'IL': 'Israele', 'AU': 'Australia', 'NZ': 'Nuova Zelanda', 'BR': 'Brasile', 'MX': 'Messico', 'AR': 'Argentina', 'CL': 'Cile', 'CO': 'Colombia', 'PE': 'Perù', 'ZA': 'Sudafrica', 'EG': 'Egitto', 'NG': 'Nigeria', 'KE': 'Kenya', 'PT': 'Portogallo', 'NL': 'Paesi Bassi', 'AT': 'Austria', 'IE': 'Irlanda', 'PL': 'Polonia', 'CZ': 'Cechia', 'HU': 'Ungheria', 'RO': 'Romania', 'GR': 'Grecia', 'SE': 'Svezia', 'NO': 'Norvegia', 'DK': 'Danimarca', 'FI': 'Finlandia'},
}}

CONTENT_LANGUAGE_NAMES = {
    'en': {'hi': 'Hindi', 'ta': 'Tamil', 'te': 'Telugu', 'ml': 'Malayalam', 'kn': 'Kannada', 'bn': 'Bengali', 'mr': 'Marathi', 'pa': 'Punjabi', 'gu': 'Gujarati', 'ur': 'Urdu', 'fr': 'French', 'en': 'English', 'de': 'German', 'es': 'Spanish', 'it': 'Italian', 'pt': 'Portuguese', 'ar': 'Arabic', 'ja': 'Japanese', 'ko': 'Korean', 'zh': 'Chinese', 'id': 'Indonesian', 'th': 'Thai', 'vi': 'Vietnamese', 'tl': 'Tagalog', 'ms': 'Malay', 'tr': 'Turkish', 'fa': 'Persian', 'he': 'Hebrew', 'ru': 'Russian', 'uk': 'Ukrainian', 'pl': 'Polish', 'nl': 'Dutch', 'sv': 'Swedish', 'da': 'Danish', 'no': 'Norwegian', 'fi': 'Finnish', 'cs': 'Czech', 'hu': 'Hungarian', 'ro': 'Romanian', 'el': 'Greek', 'sw': 'Swahili', 'af': 'Afrikaans'},
    'fr': {'hi': 'Hindi', 'ta': 'Tamoul', 'te': 'Télougou', 'ml': 'Malayalam', 'kn': 'Kannada', 'bn': 'Bengali', 'mr': 'Marathi', 'pa': 'Pendjabi', 'gu': 'Gujarati', 'ur': 'Ourdou', 'fr': 'Français', 'en': 'Anglais', 'de': 'Allemand', 'es': 'Espagnol', 'it': 'Italien', 'pt': 'Portugais', 'ar': 'Arabe', 'ja': 'Japonais', 'ko': 'Coréen', 'zh': 'Chinois', 'id': 'Indonésien', 'th': 'Thaï', 'vi': 'Vietnamien', 'tl': 'Tagalog', 'ms': 'Malais', 'tr': 'Turc', 'fa': 'Persan', 'he': 'Hébreu', 'ru': 'Russe', 'uk': 'Ukrainien', 'pl': 'Polonais', 'nl': 'Néerlandais', 'sv': 'Suédois', 'da': 'Danois', 'no': 'Norvégien', 'fi': 'Finnois', 'cs': 'Tchèque', 'hu': 'Hongrois', 'ro': 'Roumain', 'el': 'Grec', 'sw': 'Swahili', 'af': 'Afrikaans'},
    'de': {'hi': 'Hindi', 'ta': 'Tamil', 'te': 'Telugu', 'ml': 'Malayalam', 'kn': 'Kannada', 'bn': 'Bengalisch', 'mr': 'Marathi', 'pa': 'Panjabi', 'gu': 'Gujarati', 'ur': 'Urdu', 'fr': 'Französisch', 'en': 'Englisch', 'de': 'Deutsch', 'es': 'Spanisch', 'it': 'Italienisch', 'pt': 'Portugiesisch', 'ar': 'Arabisch', 'ja': 'Japanisch', 'ko': 'Koreanisch', 'zh': 'Chinesisch', 'id': 'Indonesisch', 'th': 'Thailändisch', 'vi': 'Vietnamesisch', 'tl': 'Tagalog', 'ms': 'Malaiisch', 'tr': 'Türkisch', 'fa': 'Persisch', 'he': 'Hebräisch', 'ru': 'Russisch', 'uk': 'Ukrainisch', 'pl': 'Polnisch', 'nl': 'Niederländisch', 'sv': 'Schwedisch', 'da': 'Dänisch', 'no': 'Norwegisch', 'fi': 'Finnisch', 'cs': 'Tschechisch', 'hu': 'Ungarisch', 'ro': 'Rumänisch', 'el': 'Griechisch', 'sw': 'Suaheli', 'af': 'Afrikaans'},
    'es': {'hi': 'Hindi', 'ta': 'Tamil', 'te': 'Telugu', 'ml': 'Malayalam', 'kn': 'Canarés', 'bn': 'Bengalí', 'mr': 'Maratí', 'pa': 'Panyabí', 'gu': 'Guyaratí', 'ur': 'Urdu', 'fr': 'Francés', 'en': 'Inglés', 'de': 'Alemán', 'es': 'Español', 'it': 'Italiano', 'pt': 'Portugués', 'ar': 'Árabe', 'ja': 'Japonés', 'ko': 'Coreano', 'zh': 'Chino', 'id': 'Indonesio', 'th': 'Tailandés', 'vi': 'Vietnamita', 'tl': 'Tagalo', 'ms': 'Malayo', 'tr': 'Turco', 'fa': 'Persa', 'he': 'Hebreo', 'ru': 'Ruso', 'uk': 'Ucraniano', 'pl': 'Polaco', 'nl': 'Neerlandés', 'sv': 'Sueco', 'da': 'Danés', 'no': 'Noruego', 'fi': 'Finés', 'cs': 'Checo', 'hu': 'Húngaro', 'ro': 'Rumano', 'el': 'Griego', 'sw': 'Suajili', 'af': 'Afrikáans'},
    'it': {'hi': 'Hindi', 'ta': 'Tamil', 'te': 'Telugu', 'ml': 'Malayalam', 'kn': 'Kannada', 'bn': 'Bengalese', 'mr': 'Marathi', 'pa': 'Punjabi', 'gu': 'Gujarati', 'ur': 'Urdu', 'fr': 'Francese', 'en': 'Inglese', 'de': 'Tedesco', 'es': 'Spagnolo', 'it': 'Italiano', 'pt': 'Portoghese', 'ar': 'Arabo', 'ja': 'Giapponese', 'ko': 'Coreano', 'zh': 'Cinese', 'id': 'Indonesiano', 'th': 'Thailandese', 'vi': 'Vietnamita', 'tl': 'Tagalog', 'ms': 'Malese', 'tr': 'Turco', 'fa': 'Persiano', 'he': 'Ebraico', 'ru': 'Russo', 'uk': 'Ucraino', 'pl': 'Polacco', 'nl': 'Olandese', 'sv': 'Svedese', 'da': 'Danese', 'no': 'Norvegese', 'fi': 'Finlandese', 'cs': 'Ceco', 'hu': 'Ungherese', 'ro': 'Rumeno', 'el': 'Greco', 'sw': 'Swahili', 'af': 'Afrikaans'},
}


def content_language_name(code, language='en'):
    names = CONTENT_LANGUAGE_NAMES.get(language) or CONTENT_LANGUAGE_NAMES['en']
    return names.get(code) or CONTENT_LANGUAGES.get(code, code)
