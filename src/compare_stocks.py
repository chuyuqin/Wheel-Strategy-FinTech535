"""Apply the original fixed rules to all four named stocks; no new tuning."""
from pathlib import Path
from dataclasses import asdict,replace
from datetime import datetime,timezone
import hashlib,json
import pandas as pd
import numpy as np
from backtest import Config,Market,Engine
from research import bench
from comparison_engine import DividendEngine,dividend_benchmark
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/results/comparison';RAW=ROOT/'data/raw/comparison'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def empty_dividends():return pd.DataFrame(columns=['ex_date','pay_date','announcement_date','amount'])
def market(ticker,period):
    ends=json.loads((OUT/'plan.json').read_text())['periods'][period][1]
    if ticker=='AMZN':
        if ends<'2026-01-01':return Market.load(),empty_dividends()
        return Market(pd.read_csv(ROOT/'data/raw/test2026_stock.csv',index_col=0,parse_dates=True),pd.read_csv(ROOT/'data/raw/test2026_options.csv.gz')),empty_dividends()
    folder=RAW/ticker
    capital=pd.read_csv(folder/'capital_changes.csv')
    factors=pd.to_numeric(capital['Adjustment Factor'],errors='coerce').dropna()
    if not np.allclose(factors,1):raise ValueError('Non-unit capital adjustment needs explicit deliverable handling: '+ticker)
    calendar=Market.load().stock.index if ends<'2026-01-01' else pd.read_csv(ROOT/'data/raw/test2026_stock.csv',index_col=0,parse_dates=True).index
    stock=pd.read_csv(folder/'stock.csv',index_col=0,parse_dates=True).reindex(calendar)
    if stock[['TRDPRC_1','BID','ASK']].isna().any().any():raise ValueError('Stock quotes missing on the common trading calendar: '+ticker)
    return Market(stock,pd.read_csv(folder/'options.csv.gz')),pd.read_csv(folder/'dividends_normalized.csv')
def run(m,c,symbol,divs,folder,stress=False):
    en=DividendEngine(m,c,symbol,divs,stress);d,e,s=en.run();bd,be,bs=dividend_benchmark(m,c,symbol,divs);cd,ce,cs=dividend_benchmark(m,c,symbol,divs,False)
    folder.mkdir(parents=True,exist_ok=True)
    for name,frame in [('daily',d),('blotter',e),('benchmark_daily',bd),('benchmark_blotter',be),('benchmark_cash_daily',cd),('benchmark_cash_blotter',ce),('skips',pd.DataFrame(en.skips,columns=['date','signal_date','reason']))]:frame.to_csv(folder/(name+'.csv'),index=False)
    result=dict(status='ok',config=asdict(c),symbol=symbol,dividend_assignment_stress=stress,wheel=s,buy_hold=bs,buy_hold_cash=cs,excess_return=s['total_return']-bs['total_return'],relative_wealth=s['ending_equity']/bs['ending_equity']-1,sessions=len(d))
    (folder/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False));return result,d,bd

def main():
    plan=json.loads((OUT/'plan.json').read_text());frozen=json.loads((ROOT/'docs/results/frozen_strategy.json').read_text());c=Config(**frozen['config'])
    for key,value in plan['rules'].items():assert getattr(c,key)==value,(key,value)
    summary={};parity={}
    for ticker in ['AMZN','KO','PG','VZ']:
        summary[ticker]={}
        for period,(start,end) in plan['periods'].items():
            folder=OUT/ticker/period
            try:
                m,divs=market(ticker,period);cfg=replace(c,start=start,end=end)
                base,d,bd=run(m,cfg,plan['universe'][ticker]['ric'],divs,folder)
                stress,_,_=run(m,cfg,plan['universe'][ticker]['ric'],divs,folder/'dividend_stress',True)
                base['dividend_stress']=stress;summary[ticker][period]=base
                if ticker=='AMZN':
                    old,_,_=Engine(m,cfg).run();oldb,_,_=bench(m,cfg)
                    assert np.allclose(d.equity,old.equity,atol=1e-7) and np.allclose(bd.equity,oldb.equity,atol=1e-7)
                    parity[period]=dict(wheel_unchanged=True,benchmark_unchanged=True,reference='original frozen engine rerun on the matched comparison dates')
                print(ticker,period,round(base['wheel']['total_return']*100,2),round(base['buy_hold']['total_return']*100,2),'stress',round(stress['wheel']['total_return']*100,2),flush=True)
            except Exception as exc:
                folder.mkdir(parents=True,exist_ok=True);failure=dict(status='failed',error_type=type(exc).__name__,reason=str(exc))
                (folder/'failure.json').write_text(json.dumps(failure,indent=2));summary[ticker][period]=failure
                print(ticker,period,'FAILED',type(exc).__name__,str(exc),flush=True)
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False))
    rows=[]
    for ticker,periods in summary.items():
        for period,r in periods.items():
            row=dict(ticker=ticker,period=period,status=r['status'])
            if r['status']=='ok':
                w,b=r['wheel'],r['buy_hold'];row.update(wheel_return=w['total_return'],buy_hold_drip_return=b['total_return'],buy_hold_cash_return=r['buy_hold_cash']['total_return'],excess_return=r['excess_return'],wheel_max_drawdown=w['max_drawdown'],buy_hold_max_drawdown=b['max_drawdown'],wheel_sharpe_zero_rf=w['sharpe_zero_rf'],buy_hold_sharpe_zero_rf=b['sharpe_zero_rf'],wheel_dividends=w['dividends_earned'],buy_hold_dividends=b['dividends_earned'],option_opens=w['option_opens'],contracts_sold=w['contracts_sold'],mean_capital_usage=w['mean_capital_usage'],dividend_stress_return=r['dividend_stress']['wheel']['total_return'])
            else:row.update(reason=r['reason'])
            rows.append(row)
    pd.DataFrame(rows).to_csv(OUT/'comparison.csv',index=False)
    manifest=dict(run_utc=datetime.now(timezone.utc).isoformat(),plan_sha256=sha(OUT/'plan.json'),original_freeze_sha256=sha(ROOT/'docs/results/frozen_strategy.json'),source_hashes={str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'src/comparison_engine.py',ROOT/'src/compare_stocks.py',ROOT/'src/fetch_comparison.py']},amzn_parity=parity)
    (OUT/'run_manifest.json').write_text(json.dumps(manifest,indent=2))
if __name__=='__main__':main()
