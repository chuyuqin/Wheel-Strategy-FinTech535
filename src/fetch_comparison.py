"""Retrieve the pre-specified KO/PG/VZ comparison universe through Workspace.
Workers use separate desktop sessions; every raw response is checksummed.
"""
from pathlib import Path
from datetime import date,datetime,timedelta,timezone
import argparse,calendar,hashlib,json,time,warnings
from urllib.request import urlopen
from concurrent.futures import ProcessPoolExecutor
import pandas as pd
import lseg.data as ld
ROOT=Path(__file__).resolve().parents[1];RAW=ROOT/'data/raw/comparison';OUT=ROOT/'docs/results/comparison'
FIELDS=['BID','ASK','TRDPRC_1','ACVOL_UNS','OPINT_1','DELTA','IMP_VOLT']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def cache(folder,name,req,reference=False):
    p=folder/(name+'.csv');meta=p.with_suffix('.json')
    if p.exists() and meta.exists():
        m=json.loads(meta.read_text())
        assert m['request']==req and m['sha256']==sha(p),'Existing response differs from request or hash'
        return m
    # Check the documented desktop allowance before an uncached batch. This
    # does not reset or bypass limits; completed responses remain reusable.
    with urlopen('http://localhost:9000/api/throttling/limits',timeout=10) as response:
        limits=json.load(response)
    needed=len(req['universe']) if isinstance(req['universe'],list) else 1
    if limits['daily_request_remaining']<needed:
        raise RuntimeError('Insufficient daily LSEG request allowance for this batch. Cache preserved; resume after the provider resets the allowance, or normalize the cached common window.')
    for attempt in range(3):
        try:
            d=ld.get_data(**req) if reference else ld.get_history(**req);break
        except Exception:
            if attempt==2:raise
            time.sleep(1+attempt)
    if d is None:raise ValueError('No dataframe: '+name)
    d.to_csv(p,index=not reference)
    m=dict(request=req,retrieved_utc=datetime.now(timezone.utc).isoformat(),sha256=sha(p),rows=len(d),columns=[list(x) if isinstance(x,tuple) else x for x in d.columns],library_version=ld.__version__)
    meta.write_text(json.dumps(m,indent=2));return m

def universe(ticker,spec):
    rows=[]
    strikes=[k/2 for k in range(round(spec['minimum']*2),round(spec['maximum']*2)+1,round(spec['step']*2))]
    for year in range(2023,2027):
        for month in range(1,13):
            day=next(w[4] for w in calendar.monthcalendar(year,month) if 15<=w[4]<=21);expiry=date(year,month,day)
            expiry={date(2025,4,18):date(2025,4,17),date(2026,6,19):date(2026,6,18)}.get(expiry,expiry)
            for right,codes in [('C','ABCDEFGHIJKL'),('P','MNOPQRSTUVWX')]:
                for k in strikes:
                    ric=f'{ticker}{codes[month-1]}{expiry.day}{year%100:02d}{round(k*100):05d}.U'
                    if expiry<date.today():ric+=f'^{"ABCDEFGHIJKL"[month-1]}{year%100:02d}'
                    rows.append(dict(ric=ric,expiry=expiry.isoformat(),strike=k,right=right))
    return pd.DataFrame(rows)

def worker(ticker):
    warnings.filterwarnings('ignore',message='Downcasting object dtype arrays',category=FutureWarning)
    plan=json.loads((OUT/'plan.json').read_text());spec=plan['universe'][ticker];folder=RAW/ticker;folder.mkdir(parents=True,exist_ok=True)
    u=universe(ticker,spec);u.to_csv(folder/'candidates.csv',index=False);responses=[];frames=[];coverage=[]
    ld.get_config().set_param("http.max-connections",1)
    ld.get_config().set_param("http.max-keepalive-connections",1)
    ld.get_config().set_param("http.request-timeout",60)
    ld.open_session()
    try:
        req=dict(universe=spec['ric'],fields=['TRDPRC_1','BID','ASK','ACVOL_UNS'],start='2022-12-01',end='2026-10-30',interval='1D',adjustments='unadjusted',count=2000)
        responses.append(dict(file='stock.csv',**cache(folder,'stock',req)))
        fields=['TR.DivAnnouncementDate','TR.DivExDate','TR.DivPayDate','TR.DivUnadjustedGross','TR.DivOriginalCurr','TR.DivType']
        req=dict(universe=spec['ric'],fields=fields,parameters={'SDate':'2022-12-01','EDate':'2026-10-30'})
        responses.append(dict(file='dividends.csv',**cache(folder,'dividends',req,True)))
        req=dict(universe=spec['ric'],fields=['TR.CACorpActEventType','TR.CAEffectiveDate','TR.CAAdjustmentFactor','TR.CAAdjustmentType'],parameters={'SDate':'2022-12-01','EDate':'2026-10-30'})
        responses.append(dict(file='capital_changes.csv',**cache(folder,'capital_changes',req,True)))
        for expiry,g in u.groupby('expiry'):
            req=dict(universe=g.ric.tolist(),fields=FIELDS,start=max(date(2022,12,1),date.fromisoformat(expiry)-timedelta(days=70)).isoformat(),end=min(date(2026,10,30),date.fromisoformat(expiry)).isoformat(),interval='1D',adjustments='unadjusted',count=500)
            name='options_'+expiry;responses.append(dict(file=name+'.csv',**cache(folder,name,req)))
            df=pd.read_csv(folder/(name+'.csv'),header=[0,1],index_col=0,parse_dates=True)
            observed=0
            for _,c in g.iterrows():
                if c.ric not in df.columns.get_level_values(0):continue
                x=df[c.ric].apply(pd.to_numeric,errors='coerce').dropna(how='all')
                if x.empty:continue
                observed+=1;x.index.name='date';x=x.reset_index()
                for k in ['ric','expiry','strike','right']:x[k]=c[k]
                frames.append(x)
            coverage.append(dict(expiry=expiry,candidates=len(g),observed=observed))
            print(f'{ticker} {expiry}: {observed}/{len(g)} series observed',flush=True)
    finally:ld.close_session()
    opts=pd.concat(frames,ignore_index=True).sort_values(['date','ric']);assert not opts.duplicated(['date','ric']).any()
    opts.to_csv(folder/'options.csv.gz',index=False)
    dividends=pd.read_csv(folder/'dividends.csv')
    lookup={'Dividend Announcement Date':'announcement_date','Dividend Ex Date':'ex_date','Dividend Pay Date':'pay_date','Gross Dividend Amount':'amount','Dividend Original Currency':'currency','Dividend Type':'type'}
    dividends=dividends.rename(columns=lookup)
    # The exact vendor currency header is retained in raw data and checked here.
    if 'currency' not in dividends:
        currencies=[c for c in dividends if 'Currency' in c]
        assert len(currencies)==1,currencies;dividends=dividends.rename(columns={currencies[0]:'currency'})
    for c in ['announcement_date','ex_date','pay_date']:dividends[c]=pd.to_datetime(dividends[c],errors='coerce')
    dividends['amount']=pd.to_numeric(dividends.amount,errors='coerce')
    dividends=dividends.loc[dividends.ex_date.between('2023-01-01','2026-10-30')&dividends.amount.gt(0)].copy()
    assert not dividends.ex_date.duplicated().any();assert dividends.currency.eq('USD').all();assert dividends[['ex_date','pay_date','announcement_date','amount']].notna().all().all()
    assert (dividends.announcement_date<=dividends.ex_date).all() and (dividends.pay_date>=dividends.ex_date).all()
    dividends[['announcement_date','ex_date','pay_date','amount','currency','type']].sort_values('ex_date').to_csv(folder/'dividends_normalized.csv',index=False)
    stock=pd.read_csv(folder/'stock.csv',index_col=0,parse_dates=True)
    assert str(stock.index.max().date())=='2026-10-30'
    audit=dict(ticker=ticker,stock_ric=spec['ric'],plan_sha256=sha(OUT/'plan.json'),responses=responses,coverage=coverage,option_day_records=len(opts),contracts_observed=int(opts.ric.nunique()),candidate_contracts=len(u),crossed_quotes=int((opts.BID>opts.ASK).sum()),stock_sessions=len(stock.loc['2023-01-03':'2026-10-30']),dividend_events=len(dividends),normalized_hashes={name:sha(folder/name) for name in ['options.csv.gz','dividends_normalized.csv']})
    (OUT/(ticker+'_data_audit.json')).write_text(json.dumps(audit,indent=2));return dict(ticker=ticker,records=len(opts),dividend_events=len(dividends))

def main():
    p=argparse.ArgumentParser();p.add_argument('--ticker',choices=['KO','PG','VZ']);a=p.parse_args()
    if a.ticker:print(worker(a.ticker))
    else:
        with ProcessPoolExecutor(max_workers=1) as pool:
            for r in pool.map(worker,['KO','PG','VZ']):print(r,flush=True)
if __name__=='__main__':main()
