"""Country-aware celebration dates and bounded collection display windows."""
import calendar
from datetime import date, timedelta
from dateutil.easter import easter

EVENT_IDS = ('new_year','valentine','patrick','easter','mother','memorial','father','independence',
             'labor','halloween','veteran','thanksgiving','christmas','aapi','disabilities',
             'black_history','lgbtq','latinx','women','summer')
ICONS = dict(zip(EVENT_IDS,('🎊','💘','☘️','🐰','🤱','🪖','👨','🎆','⚒️','🎃','🎖️','🦃','🎅',
                           '🌊🌺','♿','✊🏿','🏳️‍🌈','🪅','🚺','☀️')))
NAMES = {
 'fr':("Nouvel An","Saint-Valentin","Saint-Patrick","Pâques","Fête des mères","Memorial Day","Fête des pères","Fête nationale","Fête du travail","Halloween","Commémoration des anciens combattants","Thanksgiving","Noël","Patrimoine asiatique et pacifique","Journée des personnes handicapées","Histoire des Noirs","Fiertés LGBTQ+","Patrimoine latino","Histoire des femmes","Été"),
 'en':("New Year's Day","Valentine's Day","St. Patrick's Day","Easter","Mother's Day","Memorial Day","Father's Day","National Day","Labour Day","Halloween","Remembrance Day","Thanksgiving","Christmas","Asian and Pacific Islander Heritage","Day of Persons with Disabilities","Black History Month","LGBTQ+ Pride","Latinx Heritage","Women's History Month","Summer"),
 'de':("Neujahr","Valentinstag","St. Patrick's Day","Ostern","Muttertag","Memorial Day","Vatertag","Nationalfeiertag","Tag der Arbeit","Halloween","Gedenktag der Veteranen","Thanksgiving","Weihnachten","Asiatisches und pazifisches Erbe","Tag der Menschen mit Behinderungen","Schwarze Geschichte","LGBTQ+ Pride","Lateinamerikanisches Erbe","Frauengeschichte","Sommer"),
 'es':("Año Nuevo","San Valentín","San Patricio","Pascua","Día de la Madre","Memorial Day","Día del Padre","Fiesta Nacional","Día del Trabajo","Halloween","Día del Recuerdo","Acción de Gracias","Navidad","Patrimonio asiático y del Pacífico","Día de las Personas con Discapacidad","Historia Negra","Orgullo LGBTQ+","Patrimonio latino","Historia de las Mujeres","Verano"),
 'it':("Capodanno","San Valentino","San Patrizio","Pasqua","Festa della Mamma","Memorial Day","Festa del Papà","Festa Nazionale","Festa del Lavoro","Halloween","Giornata del Ricordo","Ringraziamento","Natale","Patrimonio asiatico e del Pacifico","Giornata delle Persone con Disabilità","Storia Nera","Orgoglio LGBTQ+","Patrimonio latino","Storia delle Donne","Estate")}
NATIONAL = {'FR':(7,14),'US':(7,4),'CA':(7,1),'BE':(7,21),'CH':(8,1),
            'DE':(10,3),'ES':(10,12),'IT':(6,2)}


def nth_weekday(year, month, weekday, occurrence):
    days=[date(year,month,day) for day in range(1,calendar.monthrange(year,month)[1]+1)
          if date(year,month,day).weekday()==weekday]
    return days[occurrence-1] if occurrence>0 else days[occurrence]


def celebration(event, country, year):
    fixed={'new_year':(1,1),'valentine':(2,14),'patrick':(3,17),'halloween':(10,31),
           'christmas':(12,25),'disabilities':(12,3),'aapi':(5,1),'lgbtq':(6,1),
           'latinx':(9,15),'women':(3,1),'summer':(6,1)}
    if event in fixed:return date(year,*fixed[event])
    if event=='black_history':return date(year,10 if country=='GB' else 2,1)
    if event=='easter':return easter(year)
    if event=='independence':return date(year,*NATIONAL[country]) if country in NATIONAL else None
    if event=='memorial':return nth_weekday(year,5,0,-1) if country=='US' else None
    if event=='thanksgiving':
        return nth_weekday(year,11,3,4) if country=='US' else nth_weekday(year,10,0,2) if country=='CA' else None
    if event=='mother':
        if country=='GB':return easter(year)-timedelta(days=21)
        if country=='FR':
            day=nth_weekday(year,5,6,-1)
            return nth_weekday(year,6,6,1) if day==easter(year)+timedelta(days=49) else day
        return nth_weekday(year,5,6,1 if country in ('ES','IT') else 2)
    if event=='father':
        if country=='DE':return easter(year)+timedelta(days=39)
        if country in ('IT','ES'):return date(year,3,19)
        return nth_weekday(year,6,6,1 if country=='CH' else 2 if country=='BE' else 3)
    if event=='labor':
        return nth_weekday(year,9,0,1) if country in ('US','CA') else nth_weekday(year,5,0,1) if country=='GB' else date(year,5,1)
    if event=='veteran':
        return nth_weekday(year,11,6,2) if country=='GB' else date(year,11,11) if country in ('FR','US','CA','BE') else None
    raise ValueError('collections.invalid_configuration')


def event_window(event, country, year):
    day=celebration(event,country,year)
    if day is None:return None
    if event=='new_year':start,end=date(year-1,12,26),date(year,1,4)
    elif event in ('valentine','halloween','christmas','aapi','black_history','lgbtq','women','thanksgiving','veteran'):
        start,end=day.replace(day=1),day.replace(day=calendar.monthrange(year,day.month)[1])
    elif event=='latinx':start,end=date(year,9,15),date(year,10,15)
    elif event=='summer':start,end=date(year,6,1),date(year,8,31)
    elif event=='disabilities':start,end=day-timedelta(days=1),day+timedelta(days=1)
    else:
        before,after=(11,7) if event=='independence' else (7,7) if event=='easter' else (7,3)
        start,end=day-timedelta(days=before),day+timedelta(days=after)
    return {'date':day,'start':start,'end':end}


def event_title(event, language, country):
    from core.collections_repository import STREAMING_COUNTRY_NAMES
    name=NAMES.get(language,NAMES['fr'])[EVENT_IDS.index(event)]
    if event=='independence':name+=' · '+STREAMING_COUNTRY_NAMES.get(language,STREAMING_COUNTRY_NAMES['fr'])[country]
    return name+' '+ICONS[event]


def seasonal_calendar(country, language, today):
    from core.collections_repository import STREAMING_COUNTRY_NAMES
    if country not in STREAMING_COUNTRY_NAMES['fr'] or language not in NAMES:
        raise ValueError('collections.invalid_country')
    events=[]
    for event in EVENT_IDS:
        windows=[event_window(event,country,year) for year in (today.year-1,today.year,today.year+1,today.year+2)]
        windows=[window for window in windows if window and window['end']>=today]
        window=min(windows,key=lambda row:row['start']) if windows else None
        events.append({'id':event,'name':event_title(event,language,country),'icon':ICONS[event],
            'available':window is not None,'active':bool(window and window['start']<=today<=window['end']),
            **({key:value.isoformat() for key,value in window.items()} if window else {})})
    return events
