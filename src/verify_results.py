"""Independent quantity/cash/holdings replay and source-quote checks."""
from pathlib import Path
import hashlib,json,unittest,io
from datetime import datetime
import pandas as pd
import numpy as np
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/results'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def replay(folder,raw_options,raw_stock,stress=False):
    summary=json.loads((folder/'summary.json').read_text());c=summary['config'];cash=c['initial_cash'];shares=0;short='';lots=0;basis=0;count=0
    e=pd.read_csv(folder/'blotter.csv').fillna('');d=pd.read_csv(folder/'daily.csv').fillna('')
    raw=raw_options.set_index(['date','ric'])
    for _,row in d.iterrows():
        for _,x in e.loc[e.date==row.date].iterrows():
            assert x.signal_date<x.date
            if x.action=='SELL_TO_OPEN':
                assert not short;n=int(-x.quantity)
                if x.right=='P':assert n*100*x.strike<=cash
                else:
                    assert shares>=n*100
                    if c['call_cost_floor']:assert x.strike>=basis
                if not stress:
                    rq=raw.loc[(x.date,x.instrument)];assert abs(x.price-rq.BID)<1e-8
                signal=raw.loc[(x.signal_date,x.instrument)]
                target=c['put_delta'] if x.right=='P' else c['call_delta']
                assert abs(abs(signal.DELTA)-target)<=c['delta_tolerance']+1e-9
                assert signal.ACVOL_UNS>=c['min_volume'] and signal.OPINT_1>=c['min_open_interest']
                short=x.instrument;lots=n
            elif x.action in ('BUY_TO_CLOSE','EXPIRE','ASSIGN_PUT','ASSIGN_CALL'):
                assert short==x.instrument and lots==x.quantity
                if x.action=='BUY_TO_CLOSE' and not stress:assert abs(x.price-raw.loc[(x.date,x.instrument),'ASK'])<1e-8
                short='';lots=0
            elif x.instrument=='AMZN.O':
                shares+=x.quantity;basis=x.price if x.quantity>0 else 0
            cash+=x.cashflow
            assert abs(cash-x.cash_after)<1e-6
            assert shares==x.shares_after and short==x.short_after and lots==x.short_contracts_after
            count+=1
        assert shares==row.shares and short==(row.short_put or row.covered_call) and lots==row.short_contracts
        assert abs(cash-row.cash)<1e-6 and abs(row.equity-(cash+row.stock_value-row.short_liability))<1e-6
        assert cash>=row.reserved_cash-1e-6
        assert abs(row.stock_value-shares*raw_stock.loc[row.date,'BID'])<1e-6
        assert abs(row.short_liability-row.option_ask*lots*100)<1e-6
        if row.covered_call:assert shares>=lots*100
    assert not short and shares==0 and abs(cash-summary['wheel']['ending_equity'])<1e-6
    be=pd.read_csv(folder/'benchmark_blotter.csv');bd=pd.read_csv(folder/'benchmark_daily.csv')
    assert abs(c['initial_cash']+be.cashflow.sum()-bd.equity.iloc[-1])<1e-6
    return dict(events=count,sessions=len(d),folder=str(folder.relative_to(OUT)))
def main():
    freeze=json.loads((OUT/'frozen_strategy.json').read_text())
    for file,key in [('src/backtest.py','engine_sha256'),('src/research.py','research_script_sha256'),('docs/results/research_plan.json','plan_sha256')]:assert digest(ROOT/file)==freeze[key]
    assert digest(ROOT/'data/raw/options.csv.gz')==freeze['training_input_sha256']
    old_audit=json.loads((OUT/'data_audit.json').read_text());new_audit=json.loads((OUT/'test_data_audit.json').read_text())
    assert digest(OUT/'frozen_strategy.json')==new_audit['frozen_strategy_sha256']
    assert digest(ROOT/'data/raw/test2026_options.csv.gz')==new_audit['normalized_options_sha256']
    count=0
    for x in old_audit['option_responses']:
        assert digest(ROOT/'data/raw'/x['file'])==x['sha256'];count+=1
    assert digest(ROOT/'data/raw/amzn_stock_2022_2025.csv')==old_audit['stock_response']['sha256'];count+=1
    for x in new_audit['responses']:
        assert digest(ROOT/'data/raw'/x['file'])==x['sha256'];count+=1
        assert datetime.fromisoformat(x['retrieved_utc'])>datetime.fromisoformat(freeze['frozen_utc'])
    oldopts=pd.read_csv(ROOT/'data/raw/options.csv.gz');oldstock=pd.read_csv(ROOT/'data/raw/amzn_stock_2022_2025.csv',index_col=0)
    newopts=pd.read_csv(ROOT/'data/raw/test2026_options.csv.gz');newstock=pd.read_csv(ROOT/'data/raw/test2026_stock.csv',index_col=0)
    checks=[]
    for path in sorted((OUT/'study').glob('*/*/summary.json')):checks.append(replay(path.parent,oldopts,oldstock))
    for path in sorted((OUT/'selected').glob('*/summary.json')):
        fresh=path.parent.name=='test';checks.append(replay(path.parent,newopts if fresh else oldopts,newstock if fresh else oldstock))
    for path in sorted((OUT/'stress').glob('*/summary.json')):checks.append(replay(path.parent,newopts,newstock,True))
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'));stream=io.StringIO();test=unittest.TextTestRunner(stream=stream).run(suite);assert test.wasSuccessful(),stream.getvalue()
    result=dict(status='passed',unit_tests=test.testsRun,raw_responses_verified=count,runs_replayed=len(checks),events_replayed=sum(x['events'] for x in checks),daily_portfolios_reconciled=sum(x['sessions'] for x in checks),freeze_hashes_verified=True,test_responses_retrieved_after_freeze=True,runs=checks,checks=['event cash and quantity replay','put cash collateral and call share cover','actual raw execution quotes','prior-session delta and liquidity eligibility','daily market value identities','terminal flat positions','benchmark cash reconciliation','raw response and frozen source hashes'])
    (OUT/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ['runs','checks']},indent=2))
if __name__=='__main__':main()
