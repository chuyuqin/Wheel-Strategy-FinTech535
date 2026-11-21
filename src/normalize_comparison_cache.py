"""Validate and normalize only existing cached responses; makes no API calls."""
from pathlib import Path
import json,hashlib
import pandas as pd
from fetch_comparison import universe
ROOT=Path(__file__).resolve().parents[1];RAW=ROOT/'data/raw/comparison';OUT=ROOT/'docs/results/comparison'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    plan=json.loads((OUT/'plan.json').read_text())
    for ticker in ['KO','PG','VZ']:
        folder=RAW/ticker;u=universe(ticker,plan['universe'][ticker]);responses=[];frames=[];coverage=[];missing=[]
        for name in ['stock','dividends','capital_changes']:
            p=folder/(name+'.csv');m=json.loads(p.with_suffix('.json').read_text());assert sha(p)==m['sha256'];responses.append(dict(file=p.name,**m))
        for expiry,g in u.groupby('expiry'):
            p=folder/('options_'+expiry+'.csv')
            if not p.exists() or not p.with_suffix('.json').exists():missing.append(expiry);continue
            m=json.loads(p.with_suffix('.json').read_text());assert sha(p)==m['sha256'];responses.append(dict(file=p.name,**m))
            df=pd.read_csv(p,header=[0,1],index_col=0,parse_dates=True);observed=0
            for _,c in g.iterrows():
                if c.ric not in df.columns.get_level_values(0):continue
                x=df[c.ric].apply(pd.to_numeric,errors='coerce').dropna(how='all')
                if x.empty:continue
                observed+=1;x.index.name='date';x=x.reset_index()
                for k in ['ric','expiry','strike','right']:x[k]=c[k]
                frames.append(x)
            coverage.append(dict(expiry=expiry,candidates=len(g),observed=observed))
        opts=pd.concat(frames,ignore_index=True).sort_values(['date','ric']);assert not opts.duplicated(['date','ric']).any();opts.to_csv(folder/'options.csv.gz',index=False)
        d=pd.read_csv(folder/'dividends.csv').rename(columns={'Dividend Announcement Date':'announcement_date','Dividend Ex Date':'ex_date','Dividend Pay Date':'pay_date','Gross Dividend Amount':'amount','Original Dividend Currency':'currency','Dividend Type':'type'})
        for c in ['announcement_date','ex_date','pay_date']:d[c]=pd.to_datetime(d[c],errors='coerce')
        d['amount']=pd.to_numeric(d.amount,errors='coerce');d=d.loc[d.ex_date.between('2023-01-01','2026-10-30')&d.amount.gt(0)].copy()
        assert not d.ex_date.duplicated().any() and d.currency.eq('USD').all();assert d[['ex_date','pay_date','announcement_date','amount']].notna().all().all()
        assert (d.announcement_date<=d.ex_date).all() and (d.pay_date>=d.ex_date).all()
        d[['announcement_date','ex_date','pay_date','amount','currency','type']].sort_values('ex_date').to_csv(folder/'dividends_normalized.csv',index=False)
        stock=pd.read_csv(folder/'stock.csv',index_col=0,parse_dates=True)
        audit=dict(ticker=ticker,stock_ric=plan['universe'][ticker]['ric'],plan_sha256=sha(OUT/'plan.json'),responses=responses,coverage=coverage,option_day_records=len(opts),contracts_observed=int(opts.ric.nunique()),candidate_contracts=len(u),crossed_quotes=int((opts.BID>opts.ASK).sum()),stock_sessions=len(stock.loc['2023-01-03':'2026-10-30']),dividend_events=len(d),cached_expiration_groups=len(coverage),uncached_expirations=missing,coverage_status='partial original requested universe; use only the matched common window',normalized_hashes={name:sha(folder/name) for name in ['options.csv.gz','dividends_normalized.csv']})
        (OUT/(ticker+'_data_audit.json')).write_text(json.dumps(audit,indent=2));print(ticker,len(coverage),'expiration groups;',len(opts),'option-day rows;',len(d),'dividend events')
if __name__=='__main__':main()
