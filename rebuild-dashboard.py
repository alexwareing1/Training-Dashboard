#!/usr/bin/env python3
"""
Rebuilds index.html from:
  1. hevy-export-full-history.csv        - the frozen Hevy export (base history)
  2. new-workouts-not-yet-in-export.md   - sessions logged by hand since that export
  3. dashboard-page-template.html

Usage:  python3 rebuild-dashboard.py
Everything is keyed on session date. If a date appears in both the CSV and the
log, the CSV wins and the log entry is ignored, so re-exporting from Hevy and
clearing the log is always safe.
"""
import pandas as pd, numpy as np, json, datetime as dt, re, sys, difflib, os, glob, io

HERE = os.path.dirname(os.path.abspath(__file__))
DIRS = ('/mnt/project', '/mnt/user-data/uploads', HERE, '.', '/home/claude')
def find(pattern):
    """First match for a name or glob. Tolerates upload renames like foo_2.csv."""
    for d in DIRS:
        hits = sorted(glob.glob(os.path.join(d, pattern)))
        if hits: return hits[0]
    return None

def read_csv(path):
    """Uploads sometimes gain a stray first line holding the file name.
    Skip anything above the real header row."""
    raw = open(path, encoding='utf-8-sig').read().splitlines(True)
    for i, line in enumerate(raw):
        if 'start_time' in line and 'exercise_title' in line:
            if i: print(f'  · skipped {i} junk line(s) above the header in '
                        f'{os.path.basename(path)}', file=sys.stderr)
            return pd.read_csv(io.StringIO(''.join(raw[i:])))
    raise SystemExit(f'{path} has no recognisable header row - is it the Hevy export?')

CSV  = (find('hevy-export-full-history*.csv') or find('hevyexportfullhistory*.csv')
         or find('workout_data*.csv'))
LOG  = find('new-workouts-not-yet-in-export*.md') or find('new-workouts*.md')
TPL  = (find('dashboard-page-template*.html') or find('dashboard-template*.html')
        or find('*template*.html'))
OUT  = os.environ.get('OUT') or (
    '/mnt/user-data/outputs/index.html'
    if os.path.isdir('/mnt/user-data/outputs')
    else os.path.join(HERE, 'index.html'))

GYM_SWITCH = dt.date(2026, 7, 22)
BW = 73.0

# ---------------------------------------------------------------- LOG PARSER
# ## 2026-08-28 | Push | 15:04-16:42
# Iso-Lateral Chest Press (Machine): 87.5x7, 82.5x8, 80x6, 40x4d
# Pull Up: x12, x10, x8
# suffixes: d=dropset  w=warmup  f=failure  (none = working set)
HEAD = re.compile(r'^#{1,3}\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([^|]+?)\s*'
                   r'(?:\|\s*(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})\s*)?'
                   r'(?:\|\s*guest:\s*(.+?)\s*)?'
                   r'(?:\|\s*(sick)\s*)?$', re.I)
LINE = re.compile(r'^([^:]+):\s*(.+)$')
SET  = re.compile(r'^(?:(\d+(?:\.\d+)?)\s*)?x\s*(\d+)\s*([dwf])?$', re.I)
DUR  = re.compile(r'^(\d+(?:\.\d+)?)\s*s\s*([dwf])?$', re.I)   # e.g. "34s" - a timed hold, not a rep count
TYPE = {'d':'dropset','w':'warmup','f':'failure',None:'normal'}

MARKER = 'Add new sessions below this line'
def parse_log(text, known):
    if MARKER in text:                     # ignore the instructions at the top
        text = text.split(MARKER,1)[1]
    rows, warn, cur = [], [], None
    for ln, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if not s or s.startswith(('<!--','-->','>','|','-','*','    ')): continue
        h = HEAD.match(s)
        if h:
            d, title, t0, t1, guest, sick = h.group(1), h.group(2).strip(), h.group(3), h.group(4), h.group(5), h.group(6)
            cur = {'date': d, 'title': title,
                   'start': f"{d} {t0 or '12:00'}", 'end': f"{d} {t1 or t0 or '13:00'}",
                   'venue': guest.strip() if guest else None,
                   'sick': bool(sick),
                   'idx': {}}
            continue
        m = LINE.match(s)
        if not m:
            if not s.startswith('#'): warn.append(f'line {ln}: could not read "{s[:60]}"')
            continue
        if cur is None:
            warn.append(f'line {ln}: sets before any date heading'); continue
        name, body = m.group(1).strip(), m.group(2)
        if name not in known:
            near = difflib.get_close_matches(name, known, 1, 0.75)
            if near:
                warn.append(f'line {ln}: "{name}" -> matched "{near[0]}"'); name = near[0]
            else:
                warn.append(f'line {ln}: NEW exercise "{name}" (no history to compare against)')
        i = cur['idx'].get(name, 0)
        for chunk in body.split(','):
            c = chunk.strip()
            if not c: continue
            dm = DUR.match(c)
            if dm:
                secs, sfx = float(dm.group(1)), (dm.group(2) or '').lower() or None
                rows.append({'title': cur['title'], 'start_time': cur['start'], 'end_time': cur['end'],
                             'exercise_title': name, 'set_index': i, 'set_type': TYPE[sfx],
                             'weight_kg': np.nan, 'reps': np.nan,
                             'distance_km': np.nan, 'duration_seconds': secs,
                             'description': '', 'exercise_notes': '', 'superset_id': np.nan, 'rpe': np.nan,
                             'venue': cur.get('venue'), 'sick': cur.get('sick', False)})
                i += 1; continue
            sm = SET.match(c)
            if not sm:
                warn.append(f'line {ln}: could not read set "{c}"'); continue
            w, reps, sfx = sm.group(1), int(sm.group(2)), (sm.group(3) or '').lower() or None
            rows.append({'title': cur['title'], 'start_time': cur['start'], 'end_time': cur['end'],
                         'exercise_title': name, 'set_index': i, 'set_type': TYPE[sfx],
                         'weight_kg': float(w) if w else np.nan, 'reps': reps,
                         'distance_km': np.nan, 'duration_seconds': np.nan,
                         'description': '', 'exercise_notes': '', 'superset_id': np.nan, 'rpe': np.nan,
                         'venue': cur.get('venue'), 'sick': cur.get('sick', False)})
            i += 1
        cur['idx'][name] = i
    return pd.DataFrame(rows), warn

# ---------------------------------------------------------------- LOAD
df = read_csv(CSV)
df['start_time'] = pd.to_datetime(df['start_time'], format='%d %b %Y, %H:%M')
df['end_time']   = pd.to_datetime(df['end_time'],   format='%d %b %Y, %H:%M')
base_n, base_last = len(df), df['start_time'].max().date()

added = 0
if LOG and os.path.exists(LOG):
    new, warn = parse_log(open(LOG).read(), sorted(df['exercise_title'].unique()))
    for w in warn: print('  ! ' + w, file=sys.stderr)
    if len(new):
        new['start_time'] = pd.to_datetime(new['start_time'])
        new['end_time']   = pd.to_datetime(new['end_time'])
        have = set(df['start_time'].dt.date)
        keep = new[~new['start_time'].dt.date.isin(have)]
        if len(keep) < len(new):
            dup = sorted(set(new['start_time'].dt.date) & have)
            print(f'  · already in the export, skipped: {", ".join(map(str,dup))}', file=sys.stderr)
        df = pd.concat([df, keep], ignore_index=True)
        added = keep['start_time'].dt.date.nunique()

if 'venue' not in df.columns: df['venue'] = np.nan
if 'sick' not in df.columns: df['sick'] = False
df['sick'] = df['sick'].fillna(False).astype(bool)
df['date'] = df['start_time'].dt.date
print(f'base export : {os.path.basename(CSV)} - {base_n} sets, through {base_last}')
print(f'from the log: {added} new session(s), {len(df)-base_n} sets')

# ---------------------------------------------------------------- CORRECTIONS
DOUBLE_BEFORE = {
 'Incline Bench Press (Dumbbell)': (dt.date(2025,10,17),'high','35 kg top set becomes 70 kg one session later'),
 'Seated Incline Curl (Dumbbell)': (dt.date(2025,10,24),'high','17.5 to 35, an exact doubling, same week as the press'),
 'Hammer Curl (Dumbbell)':         (dt.date(2025,10,24),'high','15 to 30, an exact doubling, same session as the curl'),
 'Shoulder Press (Dumbbell)':      (dt.date(2025,12,17),'medium','25 to 40; 40 kg per hand would beat the incline press load'),
 'Lateral Raise (Dumbbell)':       (dt.date(2025,12,17),'low','10 to 14 is not a clean doubling, and only 7 sets exist'),
}
# same idea, but additive: the number logged used to mean "plates only" (an EZ curl bar's own
# mass wasn't counted) and now means the whole bar - so old entries read light against new ones
# for no real strength reason. 7.5 kg is a typical EZ bar weight; adjust ADD_BEFORE if yours differs.
ADD_BEFORE = {
 'Skullcrusher (Barbell)': (dt.date(2026,9,7), 7.5, 'medium',
   'switched from an EZ curl bar (plates-only weight logged) to fixed-weight barbells that already '
   'include the bar - added a typical EZ bar mass to prior sessions so the trend stays comparable'),
}
df['corrected'] = False
correction_counts = {}
for ex,(cut,conf,why) in DOUBLE_BEFORE.items():
    m = (df.exercise_title==ex)&(df.date<cut)&df.weight_kg.notna()
    correction_counts[ex] = int(m.sum())
    df.loc[m,'weight_kg'] *= 2; df.loc[m,'corrected'] = True
for ex,(cut,add_kg,conf,why) in ADD_BEFORE.items():
    m = (df.exercise_title==ex)&(df.date<cut)&df.weight_kg.notna()
    correction_counts[ex] = int(m.sum())
    df.loc[m,'weight_kg'] += add_kg; df.loc[m,'corrected'] = True
df['gym'] = np.where([d < GYM_SWITCH for d in df['date']], 'Gym A', 'Gym B')

GROUPS = {
 'Chest':['Bench Press (Barbell)','Incline Bench Press (Barbell)','Incline Bench Press (Dumbbell)',
   'Incline Bench Press (Smith Machine)','Chest Press (Machine)','Iso-Lateral Chest Press (Machine)',
   'Incline Chest Press (Machine)','Butterfly (Pec Deck)','Seated Chest Flys (Cable)',
   'Low Cable Fly Crossovers','Push Up','Decline Push Up'],
 'Back':['Pull Up','Chin Up','Lat Pulldown (Cable)','Seated Cable Row - V Grip (Cable)',
   'Single Arm Cable Row','T Bar Row','Iso-Lateral High Row (Machine)','Pullover (Machine)','Dead Hang'],
 'Shoulders':['Seated Shoulder Press (Machine)','Shoulder Press (Dumbbell)','Lateral Raise (Machine)',
   'Lateral Raise (Dumbbell)','Single Arm Lateral Raise (Cable)','Front Raise (Cable)',
   'Reverse Fly Single Arm (Cable)','Rear Delt Reverse Fly (Machine)'],
 'Biceps':['Seated Incline Curl (Dumbbell)','Bicep Curl (Dumbbell)','Bicep Curl (Barbell)',
   'Bicep Curl (Machine)','Hammer Curl (Dumbbell)','Hammer Curl (Cable)','Preacher Curl (Dumbbell)',
   'Spider Curl (Dumbbell)','Hammer Preacher','Single Forearm Cable Curl','Single Arm Curl (Cable)',
   'Behind the Back Bicep Wrist Curl (Barbell)'],
 'Triceps':['Triceps Pushdown','Single Arm Triceps Pushdown (Cable)','Overhead Triceps Extension (Cable)',
   'Skullcrusher (Barbell)','Triceps Dip','Triceps Dip (Weighted)','Seated Triceps Press',
   'Seated Dip Machine','Single Arm Tricep Extension (Dumbbell)'],
 'Legs':['Leg Press Horizontal (Machine)','Leg Extension (Machine)','Standing Calf Raise (Machine)',
   'Seated Leg Curl (Machine)','Standing Leg Curls','Hip Abduction (Machine)','Hip Adduction (Machine)',
   'Squat (Barbell)','Hack Squat (Machine)','Romanian Deadlift (Barbell)'],
 'Core':['Crunch (Machine)','Ab Wheel','Plank','Side Plank','Leg Raise Parallel Bars'],
 'Cardio':['Cycling','Spinning','Running','Boxing','Stair Machine (Steps)'],
}
ex2grp = {e:g for g,l in GROUPS.items() for e in l}
unknown = sorted(set(df.exercise_title) - set(ex2grp))
if unknown:
    print('\n  ! not in any muscle group, counted as Core:', ', '.join(unknown), file=sys.stderr)
    print('    (tell me which group they belong to and I will add them)', file=sys.stderr)
df['group'] = df.exercise_title.map(lambda e: ex2grp.get(e,'Core'))

BW_FACTOR = {'Pull Up':1.0,'Chin Up':1.0,'Triceps Dip':1.0,'Triceps Dip (Weighted)':1.0,
             'Push Up':0.65,'Decline Push Up':0.75,'Leg Raise Parallel Bars':0.5,'Dead Hang':1.0}
df['bw_based'] = df.exercise_title.isin(BW_FACTOR)
df['load'] = [(w if pd.notna(w) else 0.0)+BW*BW_FACTOR[e] if e in BW_FACTOR
              else (w if pd.notna(w) else np.nan)
              for w,e in zip(df.weight_kg, df.exercise_title)]

work = df[df.group!='Cardio'].copy()
work['reps'] = work.reps.fillna(0)
work['volume'] = (work.load*work.reps).fillna(0)
# Epley extrapolates hard past ~15 reps (95kg x33 would imply a ~200kg 1RM, not credible), so
# high-rep sets still get an estimate but the reps fed into the formula are capped at 15 - a
# conservative floor rather than dropping the set from the trend entirely
work['rep_capped'] = work.reps>15
work['e1rm'] = np.where(work.reps>=1, work.load*(1+np.minimum(work.reps,15)/30), np.nan)

flags=[]
_w = work[work.set_type.isin(['normal','failure'])]
for ex,s in _w.dropna(subset=['weight_kg']).groupby('exercise_title'):
    top = s.groupby('date').weight_kg.max().sort_index()
    if len(top)<3: continue
    for i in range(1,len(top)):
        r = top.iloc[i]/top.iloc[i-1]
        if r>=1.7 or r<=0.6:
            flags.append({'ex':ex,'group':ex2grp.get(ex,'Core'),'date':str(top.index[i]),
                          'prev':float(top.iloc[i-1]),'new':float(top.iloc[i]),'ratio':round(float(r),2)})

hard = work[work.set_type.isin(['normal','failure'])].copy()
idx = hard.dropna(subset=['e1rm']).groupby(['group','exercise_title','gym','date']).e1rm.idxmax()
ex_sess = hard.loc[idx, ['group','exercise_title','gym','date','e1rm','rep_capped']].sort_values('date')
n = ex_sess.groupby(['exercise_title','gym']).date.transform('size')
ex_sess = ex_sess[n>=2].copy()
ex_sess['rel'] = ex_sess.e1rm / ex_sess.groupby(['exercise_title','gym']).e1rm.transform(
    lambda s: s.iloc[:3].median())
ex_sess['dt'] = pd.to_datetime(ex_sess.date)
T0, T1 = pd.to_datetime(df.date.min()), pd.to_datetime(df.date.max())

# sessions logged away from the usual gym (e.g. a bank-holiday drop-in) - flagged, not excluded
venue_by_date = df.dropna(subset=['venue']).drop_duplicates('date').set_index('date')['venue']
ex_sess['venue'] = ex_sess.date.map(venue_by_date)
sick_dates = set(df.loc[df.sick, 'date'])
ex_sess['sick'] = ex_sess.date.isin(sick_dates)

def smooth(d,v,win=45):
    d=np.array([x.timestamp()/86400 for x in d]); v=np.array(v,float)
    o=np.array([np.median(v[(d>=x-win/2)&(d<=x+win/2)]) for x in d])
    return [float(np.mean(o[max(0,i-1):i+2])) for i in range(len(o))]

group_index, splice = {}, {}
for g,sub in ex_sess.groupby('group'):
    s = sub.groupby(['gym','dt']).rel.mean().reset_index().sort_values('dt').reset_index(drop=True)
    s['sm']=np.nan
    for gy,part in s.groupby('gym'): s.loc[part.index,'sm']=smooth(part.dt, part.rel)
    A,B = s[s.gym=='Gym A'], s[s.gym=='Gym B']
    off = float(A.sm.iloc[-3:].mean()/B.sm.iloc[:3].mean()) if len(A) and len(B) else 1.0
    s['adj']    = np.where(s.gym=='Gym B', s.rel*off, s.rel)*100
    s['adj_sm'] = np.where(s.gym=='Gym B', s.sm *off, s.sm )*100
    group_index[g]=[{'date':d.strftime('%Y-%m-%d'),'raw':round(a,1),'sm':round(b,1),'gym':gy}
                    for d,a,b,gy in zip(s.dt,s.adj,s.adj_sm,s.gym)]
    splice[g]=round(off,3)

overall=[]
for m in pd.date_range(T0.replace(day=1)+pd.offsets.MonthBegin(0), T1, freq='MS'):
    vals=[]
    for g,pts in group_index.items():
        if g=='Core': continue
        near=[p for p in pts if abs((pd.Timestamp(p['date'])-m).days)<=38]
        if near: vals.append(np.mean([p['sm'] for p in near]))
    if len(vals)>=4: overall.append({'date':m.strftime('%Y-%m-%d'),
                                     'value':round(float(np.mean(vals)),1),'n':len(vals)})

best_e1rm={}
for g,sub in ex_sess.groupby('group'):
    idx2 = sub.groupby('dt').e1rm.idxmax()
    sel = sub.loc[idx2].sort_values('dt')
    best_e1rm[g]=[{'date':d.strftime('%Y-%m-%d'),'v':round(float(v),1),
                   **({'venue':venue_by_date[d.date()]} if d.date() in venue_by_date.index else {}),
                   **({'sick':True} if sk else {}),
                   **({'capped':True} if cap else {})}
                  for d,v,cap,sk in zip(sel.dt, sel.e1rm, sel.rep_capped, sel.sick)]

sess = df.groupby('date').agg(title=('title','first'),start=('start_time','first'),
                              end=('end_time','first')).reset_index()
sess['venue']=sess.date.map(venue_by_date)
sess['sick']=sess.date.map(df.groupby('date').sick.any())
sess['dur']=(sess.end-sess.start).dt.total_seconds()/60
sess['vol']=sess.date.map(work.groupby('date').volume.sum()).fillna(0)
sess['sets']=sess.date.map(work[work.set_type!='warmup'].groupby('date').size()).fillna(0)
sess['reps']=sess.date.map(work.groupby('date').reps.sum()).fillna(0)
sess['exs']=sess.date.map(work.groupby('date').exercise_title.nunique()).fillna(0)
sess['hour']=sess.start.dt.hour+sess.start.dt.minute/60
sess['dow']=sess.start.dt.dayofweek
sess['gym']=np.where([d<GYM_SWITCH for d in sess.date],'Gym A','Gym B')
sess['top_group']=sess.date.map(work.groupby(['date','group']).volume.sum().reset_index()
    .sort_values('volume',ascending=False).groupby('date').group.first())
sess=sess.sort_values('date').reset_index(drop=True)
sess['gap']=pd.to_datetime(sess.date).diff().dt.days

work['month']=pd.to_datetime(work.date).dt.to_period('M').astype(str)
vol_gm=(work.groupby(['month','group']).volume.sum().unstack(fill_value=0)/1000).round(2)
ms=work.groupby('month').agg(avg_w=('load','mean'),avg_reps=('reps','mean'),sets=('reps','size')).round(2)
ms['sessions']=work.groupby('month').date.nunique()

edges=list(range(0,210,10))
wdist={gy:np.histogram(sub.load,bins=edges)[0].tolist()
       for gy,sub in work.dropna(subset=['load']).groupby('gym')}
rep_bins=[1,3,6,9,12,15,21,100]
rdist=np.histogram(work[work.reps>0].reps,bins=rep_bins)[0].tolist()

pr=(hard.dropna(subset=['e1rm']).sort_values('e1rm',ascending=False)
      .groupby('exercise_title').head(1))
heavy=(hard.dropna(subset=['weight_kg']).sort_values(['weight_kg','reps'],ascending=[False,False])
      .groupby('exercise_title').head(1).set_index('exercise_title'))
# sets that ran past the 15-rep cap the e1RM formula is capped at (see footer note) -
# real work, just not comparable as a strength estimate, so surfaced separately
highrep=(hard[hard.reps>15].dropna(subset=['weight_kg']).sort_values('reps',ascending=False)
      .groupby('exercise_title').head(1).set_index('exercise_title'))
records=[]
for r in pr.itertuples():
    h=heavy.loc[r.exercise_title] if r.exercise_title in heavy.index else None
    hr=highrep.loc[r.exercise_title] if r.exercise_title in highrep.index else None
    records.append({'ex':r.exercise_title,'group':r.group,'gym':r.gym,'e1rm':round(float(r.e1rm),1),
      'date':str(r.date),'w':None if pd.isna(r.weight_kg) else float(r.weight_kg),'reps':int(r.reps),
      'bw':bool(r.bw_based),
      'top_w':None if h is None or pd.isna(h['weight_kg']) else float(h['weight_kg']),
      'top_w_reps':None if h is None else int(h['reps']),
      'top_w_date':None if h is None else str(h['date']),
      'high_rep_w':None if hr is None else float(hr['weight_kg']),
      'high_rep_reps':None if hr is None else int(hr['reps']),
      'high_rep_date':None if hr is None else str(hr['date']),
      'sets':int((work.exercise_title==r.exercise_title).sum()),
      'fixed':r.exercise_title in DOUBLE_BEFORE,
      'capped':bool(r.rep_capped),
      'venue':venue_by_date.get(r.date)})
records.sort(key=lambda x:(x['group'],-x['e1rm']))

hist={ex:[{'date':d.strftime('%Y-%m-%d'),'v':round(float(v),1),'gym':gy,
           **({'venue':ve} if pd.notna(ve) else {}),**({'sick':True} if sk else {}),
           **({'capped':True} if cap else {})}
          for d,v,gy,ve,cap,sk in zip(s.dt,s.e1rm,s.gym,s.venue,s.rep_capped,s.sick)] for ex,s in ex_sess.groupby('exercise_title')}
cardio=df[df.group=='Cardio'].groupby(['date','exercise_title']).agg(
    secs=('duration_seconds','sum'),km=('distance_km','sum')).reset_index()

payload={
 'meta':{'first':str(sess.date.min()),'last':str(sess.date.max()),'sessions':int(len(sess)),
   'sets':int(len(work)),'vol_t':round(float(work.volume.sum()/1000),1),
   'reps':int(work.reps.sum()),'hours':round(float(sess.dur.sum()/60),1),
   'exercises':int(work.exercise_title.nunique()),'switch':str(GYM_SWITCH),'bw':BW,
   'med_gap':float(sess.gap.median()),'med_dur':float(sess.dur.median()),
   'built':dt.date.today().isoformat()},
 'corrections':[{'ex':k,'from':str(v[0]),'conf':v[1],'why':v[2],'type':'multiply','amount':2,
   'sets':correction_counts[k]} for k,v in DOUBLE_BEFORE.items()] +
  [{'ex':k,'from':str(v[0]),'conf':v[2],'why':v[3],'type':'add','amount':v[1],
   'sets':correction_counts[k]} for k,v in ADD_BEFORE.items()],
 'flags':flags,'group_index':group_index,'splice':splice,'overall':overall,'best_e1rm':best_e1rm,
 'sessions':[{'date':str(r.date),'title':r.title,'dur':round(r.dur),'vol':round(r.vol/1000,2),
   'sets':int(r.sets),'reps':int(r.reps),'exs':int(r.exs),'hour':round(r.hour,2),'dow':int(r.dow),
   'gym':r.gym,'grp':r.top_group,'gap':None if pd.isna(r.gap) else int(r.gap),
   'venue':None if pd.isna(r.venue) else r.venue,
   'sick':bool(r.sick)} for r in sess.itertuples()],
 'vol_month':{'months':list(vol_gm.index),'series':{c:[float(x) for x in vol_gm[c]] for c in vol_gm.columns}},
 'month_stats':{'months':list(ms.index),'avg_w':[float(x) for x in ms.avg_w],
   'avg_reps':[float(x) for x in ms.avg_reps],'sets':[int(x) for x in ms.sets],
   'sessions':[int(x) for x in ms.sessions]},
 'wdist':{'edges':edges,**wdist},'rdist':{'bins':rep_bins,'counts':rdist},
 'records':records,'ex_history':hist,'ex_group':{e:ex2grp.get(e,'Core') for e in hist},
 'set_types':{k:int(v) for k,v in work.set_type.value_counts().items()},
 'cardio':[{'date':str(r.date),'ex':r.exercise_title,
   'mins':round(float(r.secs)/60,1) if pd.notna(r.secs) and r.secs else None,
   'km':float(r.km) if pd.notna(r.km) and r.km else None} for r in cardio.itertuples()],
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT,'w').write(open(TPL).read().replace('__DATA__', json.dumps(payload)))

print(f'\nbuilt {OUT}')
print(f'  {payload["meta"]["sessions"]} sessions · {payload["meta"]["vol_t"]} t · '
      f'{payload["meta"]["first"]} to {payload["meta"]["last"]}')
print(f'  overall index {overall[0]["value"]} -> {overall[-1]["value"]}')
print('  by group: ' + ', '.join(
    f'{g} {group_index[g][-1]["sm"]:.0f}' for g in group_index))
if flags: print(f'  {len(flags)} unresolved step-change(s) still flagged')
