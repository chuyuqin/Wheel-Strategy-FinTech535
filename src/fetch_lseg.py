"""Download a fixed monthly AMZN option grid. Requires entitled Workspace.
Daily quotes are historical observations, not verified executable NBBOs.
"""
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
import calendar, hashlib, json, argparse, time
import lseg.data as ld
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/raw'
FIELDS=['BID','ASK','TRDPRC_1','ACVOL_UNS','OPINT_1','DELTA','IMP_VOLT']
def universe():
    rows=[]
    for year in (2023,2024,2025,2026):
        for month in range(1,13):
            if year==2026 and month>2: continue
            day=next(w[4] for w in calendar.monthcalendar(year,month) if 15<=w[4]<=21)
            exp=date(year,month,day)
            if exp==date(2025,4,18): exp=date(2025,4,17)
            for right,codes in [('C','ABCDEFGHIJKL'),('P','MNOPQRSTUVWX')]:
                code=codes[month-1]
                for strike in range(40,301,5):
                    ric=f'AMZN{code}{exp.day}{year%100:02d}{strike*100:05d}.U'
                    if exp<date.today(): ric+=f'^{"ABCDEFGHIJKL"[month-1]}{year%100:02d}'
                    rows.append(dict(ric=ric,expiry=exp.isoformat(),strike=strike,right=right))
    return pd.DataFrame(rows)
def save(name,req):
    p=RAW/(name+'.csv'); meta=p.with_suffix('.json')
    if p.exists() and meta.exists():
        old=json.loads(meta.read_text())
        if old['sha256']==hashlib.sha256(p.read_bytes()).hexdigest(): return old
        raise ValueError('Cache checksum mismatch: '+name)
    subrequests=[]
    for attempt in range(3):
        try:
            df=ld.get_history(**req)
            break
        except Exception:
            if attempt<2:
                time.sleep(1)
                continue
            if not isinstance(req['universe'],list):raise
            chunks=[]
            for offset in range(0,len(req['universe']),10):
                sub=dict(req,universe=req['universe'][offset:offset+10]);subrequests.append(sub)
                part=ld.get_history(**sub)
                if part is not None:chunks.append(part)
            df=pd.concat(chunks,axis=1)
    if df is None or df.empty: raise ValueError('Empty response: '+name)
    df.to_csv(p)
    m=dict(request=req,retrieved_utc=datetime.now(timezone.utc).isoformat(),rows=len(df),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),library_version=ld.__version__,fallback_subrequests=subrequests)
    meta.write_text(json.dumps(m,indent=2));return m

def main():
    a=argparse.ArgumentParser();a.add_argument('--reuse-calls');args=a.parse_args()
    RAW.mkdir(parents=True,exist_ok=True)
    u=universe();u.to_csv(RAW/'candidate_contracts.csv',index=False)
    ld.open_session()
    try:
        save('amzn_stock_2022_2025',dict(universe='AMZN.O',fields=['OPEN_PRC','HIGH_1','LOW_1','TRDPRC_1','BID','ASK','ACVOL_UNS'],start='2022-12-01',end='2025-12-31',interval='1D',adjustments='unadjusted',count=2000))
        for (exp,right),g in u.groupby(['expiry','right']):
            name=('calls_' if right=='C' else 'puts_')+exp
            if args.reuse_calls and right=='C':
                import shutil
                for suffix in ('.csv','.json'):
                    shutil.copy2(Path(args.reuse_calls)/(name+suffix),RAW/(name+suffix))
            else:
                start=max(date(2022,12,1),date.fromisoformat(exp)-timedelta(days=70))
                end=min(date(2025,12,31),date.fromisoformat(exp))
                save(name,dict(universe=g.ric.tolist(),fields=FIELDS,start=start.isoformat(),end=end.isoformat(),interval='1D',adjustments='unadjusted',count=2000))
            print(name+' cached',flush=True)
    finally: ld.close_session()
if __name__=='__main__': main()
