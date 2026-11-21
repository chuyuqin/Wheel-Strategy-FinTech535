"""Validate response hashes and normalize the fixed candidate grid."""
from pathlib import Path
import json,hashlib
from datetime import date,timedelta
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; RAW=ROOT/'data/raw'
def main():
    u=pd.read_csv(RAW/'candidate_contracts.csv'); frames=[]; audit=[]
    for (expiry,right),g in u.groupby(['expiry','right']):
        p=RAW/(('calls_' if right=='C' else 'puts_')+expiry+'.csv')
        meta=json.loads(p.with_suffix('.json').read_text())
        assert hashlib.sha256(p.read_bytes()).hexdigest()==meta['sha256'],p.name
        df=pd.read_csv(p,header=[0,1],index_col=0,parse_dates=True)
        count=0
        for _,c in g.iterrows():
            if c.ric not in df.columns.get_level_values(0):continue
            x=df[c.ric].copy();x=x.apply(pd.to_numeric,errors='coerce')
            x=x.loc[(date.fromisoformat(expiry)-timedelta(days=70)).isoformat():'2025-12-31']
            x=x.dropna(how='all')
            if x.empty:continue
            count+=1
            x.index.name='date';x=x.reset_index();x['ric']=c.ric;x['expiry']=expiry;x['strike']=c.strike;x['right']=right
            frames.append(x)
        audit.append(dict(file=p.name,sha256=meta['sha256'],retrieved_utc=meta['retrieved_utc'],candidate_contracts=len(g),contracts_observed=count))
    stockp=RAW/'amzn_stock_2022_2025.csv';meta=json.loads(stockp.with_suffix('.json').read_text())
    assert hashlib.sha256(stockp.read_bytes()).hexdigest()==meta['sha256']
    opts=pd.concat(frames,ignore_index=True).sort_values(['date','ric'])
    assert not opts.duplicated(['date','ric']).any()
    opts.to_csv(RAW/'options.csv.gz',index=False)
    stock=pd.read_csv(stockp,index_col=0,parse_dates=True);stock=stock.loc['2023-01-03':'2025-12-31']
    valid=(opts.BID>0)&(opts.ASK>=opts.BID)
    summary=dict(stock_sessions=len(stock),first_session=str(stock.index.min().date()),last_session=str(stock.index.max().date()),candidate_contracts=len(u),contracts_observed=opts.ric.nunique(),option_day_records=len(opts),positive_two_sided_quotes=int(valid.sum()),crossed_quotes=int((opts.BID>opts.ASK).sum()),verified_responses=len(audit)+1,stock_response=meta,option_responses=audit)
    (ROOT/'docs/results/data_audit.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k not in ['stock_response','option_responses']},indent=2))
if __name__=='__main__':main()
