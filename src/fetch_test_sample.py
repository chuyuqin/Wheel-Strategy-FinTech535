"""Fetch the separate 2026 sample only after the strategy freeze exists."""
from datetime import date,timedelta,datetime,timezone
from pathlib import Path
import calendar,json,hashlib
import pandas as pd
import lseg.data as ld
from fetch_lseg import save,FIELDS,RAW,ROOT

def main():
    freeze=ROOT/'docs/results/frozen_strategy.json'
    assert freeze.exists(),'Freeze the strategy before requesting test data'
    frozen=json.loads(freeze.read_text());assert hashlib.sha256((ROOT/'src/backtest.py').read_bytes()).hexdigest()==frozen['engine_sha256']
    plan=json.loads((ROOT/'docs/results/research_plan.json').read_text());end=plan['new_test'][1]
    before=datetime.now(timezone.utc).isoformat();responses=[];frames=[];candidates=[]
    ld.open_session()
    try:
        m=save('test2026_stock',dict(universe='AMZN.O',fields=['TRDPRC_1','BID','ASK','ACVOL_UNS'],start='2025-12-01',end=end,interval='1D',adjustments='unadjusted',count=1000))
        responses.append(dict(file='test2026_stock.csv',**m));print('Stock response cached',flush=True)
        for month in range(1,13):
            day=next(w[4] for w in calendar.monthcalendar(2026,month) if 15<=w[4]<=21);exp=date(2026,month,day)
            if exp==date(2026,6,19):exp=date(2026,6,18)
            for right,codes in [('C','ABCDEFGHIJKL'),('P','MNOPQRSTUVWX')]:
                rows=[]
                for k in range(40,301,5):
                    ric=f'AMZN{codes[month-1]}{exp.day}26{k*100:05d}.U'
                    if exp<date.today():ric+=f'^{"ABCDEFGHIJKL"[month-1]}26'
                    rows.append(dict(ric=ric,expiry=exp.isoformat(),strike=k,right=right))
                candidates.extend(rows);name=f'test2026_{right}_{exp.isoformat()}'
                req=dict(universe=[x['ric'] for x in rows],fields=FIELDS,start=max(date(2025,12,1),exp-timedelta(days=70)).isoformat(),end=min(date.fromisoformat(end),exp).isoformat(),interval='1D',adjustments='unadjusted',count=500)
                # December expiries need no history before the evaluation end if
                # their 70-day history starts later. The fixed boundary is retained.
                if req['start']>req['end']:continue
                m=save(name,req);responses.append(dict(file=name+'.csv',**m))
                p=RAW/(name+'.csv');assert hashlib.sha256(p.read_bytes()).hexdigest()==m['sha256']
                data=pd.read_csv(p,header=[0,1],index_col=0,parse_dates=True)
                for info in rows:
                    if info['ric'] not in data.columns.get_level_values(0):continue
                    x=data[info['ric']].apply(pd.to_numeric,errors='coerce').dropna(how='all')
                    if x.empty:continue
                    x.index.name='date';x=x.reset_index()
                    for k,v in info.items():x[k]=v
                    frames.append(x)
                print(name+' cached',flush=True)
    finally:ld.close_session()
    u=pd.DataFrame(candidates);u.to_csv(RAW/'test2026_candidates.csv',index=False)
    options=pd.concat(frames,ignore_index=True).sort_values(['date','ric']);assert not options.duplicated(['date','ric']).any()
    options.to_csv(RAW/'test2026_options.csv.gz',index=False)
    stock=pd.read_csv(RAW/'test2026_stock.csv',index_col=0,parse_dates=True).loc[plan['new_test'][0]:end]
    assert str(stock.index.max().date())==end,'Requested test end not available; do not silently shorten the test'
    audit=dict(fetch_started_utc=before,frozen_utc=frozen['frozen_utc'],frozen_strategy_sha256=hashlib.sha256(freeze.read_bytes()).hexdigest(),responses=responses,stock_sessions=len(stock),first_session=str(stock.index.min().date()),last_session=str(stock.index.max().date()),option_day_records=len(options),contracts_observed=int(options.ric.nunique()),candidate_contracts=len(u),crossed_quotes=int((options.BID>options.ASK).sum()),normalized_options_sha256=hashlib.sha256((RAW/'test2026_options.csv.gz').read_bytes()).hexdigest())
    (ROOT/'docs/results/test_data_audit.json').write_text(json.dumps(audit,indent=2));print('Test sample normalized',flush=True)
if __name__=='__main__':main()
