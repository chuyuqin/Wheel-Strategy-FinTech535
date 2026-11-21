"""Independent dividend, quantity, cash and valuation replay for the comparison."""
from pathlib import Path
from datetime import datetime
import json,hashlib,unittest,io
import pandas as pd
import numpy as np
from compare_stocks import market
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/results/comparison';RAW=ROOT/'data/raw/comparison'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def replay(folder,m,dividends,benchmark=False,cash_benchmark=False,stress=False):
    prefix='benchmark_cash_' if cash_benchmark else ('benchmark_' if benchmark else '')
    d=pd.read_csv(folder/(prefix+'daily.csv')).fillna('');e=pd.read_csv(folder/(prefix+'blotter.csv')).fillna('')
    summary=json.loads((folder/'summary.json').read_text());symbol=summary['symbol'];c=summary['config'];cash=c['initial_cash'];shares=0;short='';lots=0;pending={};count=0
    divs=dividends.copy();divs['ex_date']=pd.to_datetime(divs.ex_date).dt.strftime('%Y-%m-%d');divs['pay_date']=pd.to_datetime(divs.pay_date).dt.strftime('%Y-%m-%d');divs['announcement_date']=pd.to_datetime(divs.announcement_date).dt.strftime('%Y-%m-%d')
    for _,row in d.iterrows():
        for _,x in e.loc[e.date.eq(row.date)].iterrows():
            if x.action=='DIVIDEND_ENTITLEMENT':
                div=divs.loc[divs.ex_date.eq(x.date)];assert len(div)==1 and shares>0
                expected=shares*float(div.amount.iloc[0]);assert abs(x.dividend_amount-expected)<1e-6
                assert abs(x.entitled_shares-shares)<1e-7
                assert x.dividend_id not in pending
                pending[x.dividend_id]=dict(amount=expected,pay_date=div.pay_date.iloc[0]);assert x.cashflow==0
            elif x.action=='DIVIDEND_PAID':
                claim=pending.pop(x.dividend_id);assert abs(x.cashflow-claim['amount'])<1e-6 and x.date>=claim['pay_date']
                assert x.date==d.loc[d.date.ge(claim['pay_date']),'date'].iloc[0]
            elif x.instrument==symbol:
                assert abs(x.cashflow+x.quantity*x.price+x.fee)<1e-6
                if x.action in ('BUY_STOCK','REINVEST_DIVIDEND'):assert abs(x.price-float(m.stock.loc[pd.Timestamp(x.date),'ASK']))<1e-8
                if x.action=='REINVEST_DIVIDEND':assert not cash_benchmark and abs(x.cashflow+cash)<1e-6
                shares+=x.quantity
            elif x.action=='SELL_TO_OPEN':
                assert not short and x.signal_date<x.date
                n=int(-x.quantity);meta=m.meta.loc[x.instrument]
                if meta.right=='P':
                    assert n*100*float(meta.strike)<=cash
                    assert n==int(cash*c['allocation_fraction']//(float(meta.strike)*100))
                else:assert shares>=100*n
                q=m.quote(pd.Timestamp(x.date),x.instrument);assert abs(x.price-float(q.BID))<1e-8
                signal=m.quote(pd.Timestamp(x.signal_date),x.instrument);target=c['put_delta'] if meta.right=='P' else c['call_delta']
                assert abs(abs(signal.DELTA)-target)<=c['delta_tolerance']+1e-9
                assert signal.ACVOL_UNS>=c['min_volume'] and signal.OPINT_1>=c['min_open_interest']
                assert abs(x.cashflow+x.quantity*x.price*100+x.fee)<1e-6
                short=x.instrument;lots=n
            elif x.action in ('BUY_TO_CLOSE','EXPIRE','ASSIGN_PUT','ASSIGN_CALL'):
                assert short==x.instrument and lots==x.quantity
                if x.action=='BUY_TO_CLOSE':assert abs(x.price-float(m.quote(pd.Timestamp(x.date),x.instrument).ASK))<1e-8
                if x.get('reason','')=='pre_dividend_assignment':
                    assert stress and x.action=='ASSIGN_CALL'
                    trigger=divs.loc[divs.ex_date.eq(x.trigger_ex_date)];assert len(trigger)==1
                    assert trigger.announcement_date.iloc[0]<=x.date<x.trigger_ex_date
                    nextdate=m.stock.index[m.stock.index>pd.Timestamp(x.date)][0];assert str(nextdate.date())==x.trigger_ex_date
                    q=m.quote(pd.Timestamp(x.date),x.instrument);k=float(m.meta.loc[x.instrument,'strike']);spot=float(m.stock.loc[pd.Timestamp(x.date),'TRDPRC_1']);intrinsic=spot-k
                    assert intrinsic>=.01 and max(0,q.BID-intrinsic)<=float(trigger.amount.iloc[0])+1e-9
                short='';lots=0
            cash+=x.cashflow
            assert abs(cash-x.cash_after)<1e-6 and abs(shares-x.shares_after)<1e-6
            assert abs(sum(t['amount'] for t in pending.values())-x.dividend_receivable_after)<1e-6
            if not benchmark and not cash_benchmark:assert short==x.short_after and lots==x.short_contracts_after
            count+=1
        claim=sum(x['amount'] for x in pending.values())
        assert abs(cash-row.cash)<1e-6 and abs(shares-row.shares)<1e-6 and abs(claim-row.dividend_receivable)<1e-6
        stock_value=shares*float(m.stock.loc[pd.Timestamp(row.date),'BID']);assert abs(row.stock_value-stock_value)<1e-6
        liability=row.get('short_liability',0)
        assert abs(row.equity-cash-stock_value-claim+liability)<1e-6
        if not benchmark and not cash_benchmark:
            assert short==(row.short_put or row.covered_call) and lots==row.short_contracts
            assert cash>=row.reserved_cash-1e-6
            assert abs(liability-100*lots*row.option_ask)<1e-6
            if row.covered_call:assert shares>=100*lots
    assert abs(shares)<1e-6 and not short
    return dict(path=str(folder.relative_to(OUT)),account=prefix or 'wheel',sessions=len(d),events=count)
def main():
    summary=json.loads((OUT/'summary.json').read_text());manifest=json.loads((OUT/'run_manifest.json').read_text());plan=json.loads((OUT/'plan.json').read_text())
    assert sha(OUT/'plan.json')==manifest['plan_sha256']
    for p,h in manifest['source_hashes'].items():assert sha(ROOT/p)==h
    assert sha(ROOT/'docs/results/frozen_strategy.json')==manifest['original_freeze_sha256']
    raw_count=0
    for ticker in ['KO','PG','VZ']:
        audit=json.loads((OUT/(ticker+'_data_audit.json')).read_text())
        for x in audit['responses']:assert sha(RAW/ticker/x['file'])==x['sha256'];raw_count+=1
        for name,h in audit['normalized_hashes'].items():assert sha(RAW/ticker/name)==h
    checked=[]
    for ticker,periods in summary.items():
        for period,result in periods.items():
            if result['status']!='ok':continue
            m,divs=market(ticker,period);folder=OUT/ticker/period
            checked.extend([replay(folder,m,divs),replay(folder,m,divs,True),replay(folder,m,divs,cash_benchmark=True),replay(folder/'dividend_stress',m,divs,stress=True)])
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'));stream=io.StringIO();test=unittest.TextTestRunner(stream=stream).run(suite);assert test.wasSuccessful(),stream.getvalue()
    result=dict(status='passed',unit_tests=test.testsRun,comparison_raw_responses_verified=raw_count,account_runs_replayed=len(checked),events_replayed=sum(x['events'] for x in checked),daily_portfolios_reconciled=sum(x['sessions'] for x in checked),all_four_tickers_reported=set(summary)==set(plan['universe']),failed_cases=[dict(ticker=t,period=p,**r) for t,v in summary.items() for p,r in v.items() if r['status']!='ok'],amzn_parity=manifest['amzn_parity'],checks=['ex-date ownership and dividend amount','payment-date cash availability','unpaid dividend receivables','dividend reinvestment at observed ask','pre-dividend stress uses announced information only','cash and option/share quantity replay','put collateral and covered calls','daily equity and terminal liquidation','verified raw response hashes'],runs=checked)
    (OUT/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ['runs','checks']},indent=2))
if __name__=='__main__':main()
