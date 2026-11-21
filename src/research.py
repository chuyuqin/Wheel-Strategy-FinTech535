"""Chronological parameter study. Freeze rules before fetching a new sample."""
from pathlib import Path
from dataclasses import asdict,replace
from datetime import datetime,timezone
import argparse,hashlib,json,itertools
import pandas as pd
from backtest import Config,Market,Engine,statistics
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/results'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,allow_nan=False))
def grid():
    for put,call,tenor in itertools.product([.30,.45],[.15,.30],[21,35]):
        yield f'p{round(put*100)}_c{round(call*100)}_d{tenor}',Config(initial_cash=50000,put_delta=put,call_delta=call,delta_tolerance=.10,allocation_fraction=.90,call_cost_floor=True,dte_target=tenor,dte_min=14 if tenor==21 else 28,dte_max=28 if tenor==21 else 45,min_volume=100,min_open_interest=500)
def bench(m,c):
    dates=m.stock.loc[c.start:c.end].index;qty=c.initial_cash/float(m.stock.loc[dates[0],'ASK']);cash=0;rows=[]
    for i,date in enumerate(dates):
        value=qty*float(m.stock.loc[date,'BID']);n=qty
        if i==len(dates)-1:cash=value;value=0;n=0
        rows.append(dict(date=str(date.date()),equity=cash+value,cash=cash,shares=n,stock_value=value))
    d=pd.DataFrame(rows);s=statistics(d,c)
    ev=pd.DataFrame([dict(date=str(dates[0].date()),action='BUY_STOCK',quantity=qty,price=float(m.stock.loc[dates[0],'ASK']),fee=0,cashflow=-c.initial_cash),dict(date=str(dates[-1].date()),action='SELL_STOCK',quantity=-qty,price=float(m.stock.loc[dates[-1],'BID']),fee=0,cashflow=float(d.equity.iloc[-1]))])
    return d,ev,s

def run(m,c,folder):
    en=Engine(m,c);d,e,s=en.run();b,be,bs=bench(m,c)
    folder.mkdir(parents=True,exist_ok=True)
    d.to_csv(folder/'daily.csv',index=False);e.to_csv(folder/'blotter.csv',index=False);b.to_csv(folder/'benchmark_daily.csv',index=False);be.to_csv(folder/'benchmark_blotter.csv',index=False)
    pd.DataFrame(en.skips,columns=['date','signal_date','reason']).to_csv(folder/'skips.csv',index=False)
    result=dict(config=asdict(c),wheel=s,buy_hold=bs,excess_return=s['total_return']-bs['total_return'],relative_wealth=s['ending_equity']/bs['ending_equity']-1,sessions=len(d))
    dump(folder/'summary.json',result);return result

def select():
    m=Market.load();plan=json.loads((OUT/'research_plan.json').read_text());rows=[]
    for name,c in grid():
        result=run(m,replace(c,start=plan['training'][0],end=plan['training'][1]),OUT/'study/training'/name)
        rows.append(dict(id=name,config=asdict(c),training=result))
    rows.sort(key=lambda x:(-x['training']['wheel']['total_return'],-x['training']['wheel']['max_drawdown'],x['id']))
    winner=rows[0]
    freeze=dict(frozen_utc=datetime.now(timezone.utc).isoformat(),selected_id=winner['id'],config=winner['config'],selection_rule=plan['selection'],plan_sha256=digest(OUT/'research_plan.json'),engine_sha256=digest(ROOT/'src/backtest.py'),research_script_sha256=digest(ROOT/'src/research.py'),training_input_sha256=digest(ROOT/'data/raw/options.csv.gz'),training_ranking=[dict(id=r['id'],return_=r['training']['wheel']['total_return'],max_drawdown=r['training']['wheel']['max_drawdown']) for r in rows])
    dump(OUT/'frozen_strategy.json',freeze);dump(ROOT/'config.json',winner['config'])
    for row in rows:
        c=Config(**row['config'])
        for label,key in [('validation','validation'),('diagnostic','previously_seen_diagnostic')]:
            row[label]=run(m,replace(c,start=plan[key][0],end=plan[key][1]),OUT/'study'/label/row['id'])
    dump(OUT/'parameter_study.json',rows)
    periods={}
    c=Config(**winner['config'])
    for name,start,end,label in [('training',*plan['training'],'2023 · parameter selection'),('validation',*plan['validation'],'2024 · chronological validation'),('diagnostic',*plan['previously_seen_diagnostic'],'2025 · previously seen diagnostic'),('historical','2023-01-03','2025-12-31','2023–2025 · retrospective study')]:
        periods[name]=dict(label=label,**run(m,replace(c,start=start,end=end),OUT/'selected'/name))
    dump(OUT/'periods.json',periods)
    print(json.dumps(dict(selected_id=winner['id'],training_return=winner['training']['wheel']['total_return'],periods={k:dict(wheel=v['wheel']['total_return'],buy_hold=v['buy_hold']['total_return']) for k,v in periods.items()}),indent=2))

def test():
    freeze=json.loads((OUT/'frozen_strategy.json').read_text());plan=json.loads((OUT/'research_plan.json').read_text())
    assert digest(ROOT/'src/backtest.py')==freeze['engine_sha256'],'Engine changed after freeze'
    assert digest(ROOT/'src/research.py')==freeze['research_script_sha256'],'Selection script changed after freeze'
    assert digest(OUT/'research_plan.json')==freeze['plan_sha256'],'Plan changed after freeze'
    m=Market(pd.read_csv(ROOT/'data/raw/test2026_stock.csv',index_col=0,parse_dates=True),pd.read_csv(ROOT/'data/raw/test2026_options.csv.gz'))
    start,end=plan['new_test'];c=replace(Config(**freeze['config']),start=start,end=end)
    result=run(m,c,OUT/'selected/test')
    periods=json.loads((OUT/'periods.json').read_text());periods['test']=dict(label='2026 YTD · held-out historical test',**result)
    dump(OUT/'periods.json',periods)
    stress=[]
    for label,changes in [('Wider fills',dict(extra_spread_fraction=.5)),('Early assignment',dict(early_assignment_stress=True))]:
        name=label.lower().replace(' ','_');stress.append(dict(label=label,**run(m,replace(c,**changes),OUT/'stress'/name)))
    dump(OUT/'stress_tests.json',stress)
    print(json.dumps(dict(test_wheel=result['wheel'],test_buy_hold=result['buy_hold']),indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['select','test']);a=p.parse_args()
    select() if a.stage=='select' else test()
