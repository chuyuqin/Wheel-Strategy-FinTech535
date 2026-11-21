"""Physical-settlement wheel with prior-session selection.
Baseline: hold to expiry, cash-secured puts and covered calls, no leverage.
Observed daily sides proxy execution; they are not verified intraday fills.
"""
from dataclasses import dataclass,asdict,replace
from pathlib import Path
from collections import Counter
import json,hashlib,math
import pandas as pd
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
@dataclass
class Config:
    start:str='2023-01-03';end:str='2025-12-31';initial_cash:float=50000
    delta_target:float=.30;delta_min:float=.15;delta_max:float=.40
    dte_min:int=21;dte_max:int=45;dte_target:int=30
    max_relative_spread:float=.25;max_absolute_spread:float=1
    min_volume:int=1;min_open_interest:int=100
    option_fee:float=.65;extra_spread_fraction:float=0
    cash_rate:float=0;roll_dte:int=0;early_assignment_stress:bool=False
    max_carried_sessions:int=2
    allocation_fraction:float=0
    put_delta:float=0;call_delta:float=0;delta_tolerance:float=.1
    call_cost_floor:bool=False

def quote_ok(q,entry=False,c=None):
    if q is None or pd.isna(q.BID) or pd.isna(q.ASK):return False
    if q.BID<0 or q.ASK<=0 or q.ASK<q.BID:return False
    if not entry:return True
    mid=(q.ASK+q.BID)/2
    return q.BID>0 and q.ASK-q.BID<=c.max_absolute_spread and (q.ASK-q.BID)/mid<=c.max_relative_spread

def ask_ok(q):
    return q is not None and pd.notna(q.ASK) and q.ASK>=0 and not (pd.notna(q.BID) and q.BID>q.ASK)

def fill(q,buy,c):
    if not (ask_ok(q) if buy else quote_ok(q)):raise ValueError('Missing or invalid execution quote')
    width=float(q.ASK-q.BID) if quote_ok(q) else max(.01,.2*float(q.ASK))
    return float(q.ASK+c.extra_spread_fraction*width if buy else max(0,q.BID-c.extra_spread_fraction*width))

class Market:
    def __init__(self,stock,options):
        self.stock=stock.sort_index();self.options=options.copy()
        for col in ['date','expiry']:self.options[col]=pd.to_datetime(self.options[col])
        assert not self.options.duplicated(['date','ric']).any()
        self.chains={d:g.set_index('ric',drop=False) for d,g in self.options.groupby('date')}
        self.empty=self.options.iloc[:0].set_index('ric',drop=False)
        self.meta=self.options[['ric','expiry','strike','right']].drop_duplicates().set_index('ric')
        assert not self.meta.index.duplicated().any()
    @classmethod
    def load(cls):return cls(pd.read_csv(ROOT/'data/raw/amzn_stock_2022_2025.csv',index_col=0,parse_dates=True),pd.read_csv(ROOT/'data/raw/options.csv.gz'))
    def quote(self,date,ric):
        g=self.chains.get(date,self.empty)
        return g.loc[ric] if ric in g.index else None
    def select(self,date,right,c):
        g=self.chains.get(date,self.empty).copy();g['dte']=(g.expiry-date).dt.days
        spot=float(self.stock.loc[date,'TRDPRC_1']);w=g.ASK-g.BID
        ok=(g.right==right)&g.dte.between(c.dte_min,c.dte_max)&g.DELTA.abs().between(c.delta_min,c.delta_max)
        ok&=(g.DELTA<0 if right=='P' else g.DELTA>0)
        ok&=(g.strike<spot if right=='P' else g.strike>spot)
        ok&=(g.BID>0)&(g.ASK>=g.BID)&(w<=c.max_absolute_spread)&(w/((g.ASK+g.BID)/2)<=c.max_relative_spread)
        ok&=g.ACVOL_UNS.ge(c.min_volume)&g.OPINT_1.ge(c.min_open_interest)
        g=g.loc[ok].copy();g['delta_gap']=(g.DELTA.abs()-c.delta_target).abs();g['dte_gap']=(g.dte-c.dte_target).abs();g['tie']=g.ric
        return g.sort_values(['delta_gap','dte_gap','strike','tie'])

class Engine:
    def __init__(self,m,c):
        self.m=m;self.c=c;self.cash=c.initial_cash;self.shares=0;self.short=None;self.short_lots=0;self.stock_basis=0
        self.events=[];self.daily=[];self.skips=[];self.last_mark=None
        self.date=None;self.signal=None;self.cycle=0;self.open_trade=None
    def event(self,action,instrument,qty,price=0,fee=0,reason='',cashflow=None,**extra):
        mult=1 if instrument in ('AMZN.O','CASH') else 100
        cf=-qty*price*mult-fee if cashflow is None else cashflow
        self.cash+=cf
        row=dict(event_id=len(self.events)+1,date=str(self.date.date()),signal_date=str(self.signal.date()),cycle=self.cycle,action=action,instrument=instrument,quantity=qty,multiplier=mult,price=float(price),fee=float(fee),cashflow=float(cf),cash_after=float(self.cash),shares_after=self.shares,short_after=self.short or '',short_contracts_after=self.short_lots,stock_basis_after=self.stock_basis,reason=reason)
        if instrument in self.m.meta.index:
            info=self.m.meta.loc[instrument];row.update(strike=float(info.strike),expiry=str(info.expiry.date()),right=info.right)
        row.update(extra);self.events.append(row)
        assert self.cash>=-1e-7
    def skip(self,reason):self.skips.append(dict(date=str(self.date.date()),signal_date=str(self.signal.date()),reason=reason))
    def open(self):
        right='P' if self.shares==0 else 'C'
        target=self.c.put_delta if right=='P' else self.c.call_delta
        select_config=replace(self.c,delta_target=target,delta_min=max(.01,target-self.c.delta_tolerance),delta_max=min(.60,target+self.c.delta_tolerance)) if target else self.c
        choices=self.m.select(self.signal,right,select_config)
        if right=='C' and self.c.call_cost_floor:choices=choices.loc[choices.strike>=self.stock_basis]
        if choices.empty:self.skip('no_eligible_'+right);return
        # Pick once using only signal data; never substitute using execution data.
        candidate=choices.iloc[0];ric=candidate.ric;q=self.m.quote(self.date,ric)
        if not quote_ok(q,True,self.c):self.skip('execution_quote_rejected');return
        if (candidate.expiry-self.date).days<=0:self.skip('expired_before_fill');return
        if right=='P' and candidate.strike*100>self.cash:self.skip('insufficient_collateral');return
        assert self.shares>=100 and self.shares%100==0 if right=='C' else self.shares==0
        lots=(int(self.cash*self.c.allocation_fraction//(candidate.strike*100)) if self.c.allocation_fraction else 1) if right=='P' else self.shares//100
        if lots<1:self.skip('insufficient_allocation');return
        if right=='P' and self.cycle==0:self.cycle=1
        self.short=ric;self.short_lots=lots;self.open_trade=len(self.events)+1
        self.event('SELL_TO_OPEN',ric,-lots,fill(q,False,self.c),self.c.option_fee*lots,'cash_secured_put' if right=='P' else 'covered_call',bid=float(q.BID),ask=float(q.ASK),signal_delta=float(candidate.DELTA),signal_volume=float(candidate.ACVOL_UNS),signal_open_interest=float(candidate.OPINT_1),signal_dte=int(candidate.dte),signal_bid=float(candidate.BID),signal_ask=float(candidate.ASK))
        self.last_mark=None
    def close(self,reason):
        ric=self.short;q=self.m.quote(self.date,ric)
        if not ask_ok(q):
            if reason=='terminal_liquidation':raise ValueError('Cannot liquidate without observed quote')
            self.skip('roll_close_quote_missing');return False
        lots=self.short_lots;self.short=None;self.short_lots=0
        self.event('BUY_TO_CLOSE',ric,lots,fill(q,True,self.c),self.c.option_fee*lots,reason,bid=float(q.BID),ask=float(q.ASK),open_event_id=self.open_trade)
        return True
    def settle(self,reason):
        ric=self.short;info=self.m.meta.loc[ric];spot=float(self.m.stock.loc[self.date,'TRDPRC_1'])
        itm=(info.strike-spot if info.right=='P' else spot-info.strike)>=.01-1e-9
        if reason=='early_assignment_stress':itm=True
        lots=self.short_lots;self.short=None;self.short_lots=0
        if itm:
            self.event('ASSIGN_PUT' if info.right=='P' else 'ASSIGN_CALL',ric,lots,reason=reason,open_event_id=self.open_trade)
            qty=100*lots if info.right=='P' else -100*lots;self.shares+=qty
            self.stock_basis=float(info.strike) if qty>0 else 0
            self.event('RECEIVE_SHARES' if qty>0 else 'DELIVER_SHARES','AMZN.O',qty,float(info.strike),reason=reason,option_ric=ric)
            if qty<0:self.cycle+=1
        else:self.event('EXPIRE',ric,lots,reason='expiry_otm',open_event_id=self.open_trade)
    def run(self):
        all_dates=self.m.stock.index;dates=all_dates[(all_dates>=self.c.start)&(all_dates<=self.c.end)]
        previous_date=None
        for step,date in enumerate(dates):
            self.date=date;idx=all_dates.get_loc(date);assert idx>0
            self.signal=all_dates[idx-1];assert self.signal<date
            if previous_date is not None and self.c.cash_rate:
                interest=self.cash*self.c.cash_rate*(date-previous_date).days/365
                self.event('INTEREST','CASH',0,reason='constant_rate_scenario',cashflow=interest)
            ending=step==len(dates)-1;blocked=False
            if self.short and self.c.early_assignment_stress:
                q=self.m.quote(self.signal,self.short);info=self.m.meta.loc[self.short];spot=float(self.m.stock.loc[self.signal,'TRDPRC_1'])
                intrinsic=max(0,info.strike-spot if info.right=='P' else spot-info.strike)
                if quote_ok(q) and intrinsic>=.01 and q.BID-intrinsic<=.05:
                    self.settle('early_assignment_stress');blocked=True
            if self.short and not ending and self.c.roll_dte and (self.m.meta.loc[self.short,'expiry']-self.signal).days<=self.c.roll_dte:
                blocked=not self.close('scheduled_roll')
            if ending:
                if self.short:self.close('terminal_liquidation')
                if self.shares:
                    q=self.m.stock.loc[date];qty=-self.shares;self.shares=0;self.stock_basis=0
                    self.event('SELL_STOCK','AMZN.O',qty,fill(q,False,self.c),reason='terminal_liquidation')
            elif not self.short and not blocked:self.open()
            if self.short and self.m.meta.loc[self.short,'expiry']<=date:self.settle('expiry_assignment')
            carried=False;mark=0
            if self.short:
                q=self.m.quote(date,self.short)
                if ask_ok(q):mark=float(q.ASK);self.last_mark=(self.short,mark,step)
                elif self.last_mark and self.last_mark[0]==self.short and step-self.last_mark[2]<=self.c.max_carried_sessions:
                    mark=self.last_mark[1];carried=True
                else:raise ValueError(f'Unresolved valuation gap {date} {self.short}')
            sq=self.m.stock.loc[date];assert quote_ok(sq)
            stock_value=self.shares*float(sq.BID);liability=100*self.short_lots*mark
            info=self.m.meta.loc[self.short] if self.short else None
            collateral=100*self.short_lots*float(info.strike) if info is not None and info.right=='P' else 0
            assert self.shares>=0 and self.shares%100==0 and self.cash+1e-7>=collateral
            if info is not None and info.right=='C':assert self.shares>=100*self.short_lots
            self.daily.append(dict(date=str(date.date()),cash=self.cash,shares=self.shares,short_contracts=self.short_lots,stock_basis=self.stock_basis,stock_bid=float(sq.BID),stock_close=float(sq.TRDPRC_1),stock_value=stock_value,short_put=self.short if info is not None and info.right=='P' else '',covered_call=self.short if info is not None and info.right=='C' else '',option_strike=float(info.strike) if info is not None else 0,option_expiry=str(info.expiry.date()) if info is not None else '',option_ask=mark,short_liability=liability,reserved_cash=collateral,free_cash=self.cash-collateral,equity=self.cash+stock_value-liability,carried_mark=int(carried),state='SHORT_PUT' if collateral else ('COVERED_CALL' if self.short else ('SHARES' if self.shares else 'CASH'))))
            previous_date=date
        d=pd.DataFrame(self.daily);e=pd.DataFrame(self.events) if self.events else pd.DataFrame(columns=["date","action","instrument","quantity","price","fee","cashflow"])
        assert not self.short and self.shares==0
        assert math.isclose(self.cash,self.c.initial_cash+e.cashflow.sum(),abs_tol=1e-6)
        d['daily_cashflow']=d.date.map(e.groupby('date').cashflow.sum()).fillna(0)
        assert np.allclose(d.cash,self.c.initial_cash+d.daily_cashflow.cumsum())
        s=statistics(d,self.c)
        s.update(contracts_sold=int(-e.loc[e.action.eq('SELL_TO_OPEN'),'quantity'].sum()),mean_capital_usage=float(((d.reserved_cash+d.stock_value)/d.equity).mean()),option_opens=int(e.action.eq('SELL_TO_OPEN').sum()),option_closes=int(e.action.eq('BUY_TO_CLOSE').sum()),put_assignments=int(e.action.eq('ASSIGN_PUT').sum()),call_assignments=int(e.action.eq('ASSIGN_CALL').sum()),expirations=int(e.action.eq('EXPIRE').sum()),fees=float(e.fee.sum()),premium_received=float((-e.loc[e.action.eq('SELL_TO_OPEN'),'quantity']*e.loc[e.action.eq('SELL_TO_OPEN'),'price']).sum()*100),buyback_cost=float((e.loc[e.action.eq('BUY_TO_CLOSE'),'quantity']*e.loc[e.action.eq('BUY_TO_CLOSE'),'price']).sum()*100),stock_cashflow=float(e.loc[e.instrument.eq('AMZN.O'),'cashflow'].sum()),carried_mark_days=int(d.carried_mark.sum()),skip_reasons=dict(Counter(x['reason'] for x in self.skips)),stock_exposure_fraction=float(d.shares.gt(0).mean()),mean_reserved_cash=float(d.reserved_cash.mean()),events=len(e))
        assert math.isclose(s['net_profit'],s['premium_received']-s['buyback_cost']+s['stock_cashflow']-s['fees']+float(e.loc[e.action.eq('INTEREST'),'cashflow'].sum()),abs_tol=1e-6)
        return d,e,s

def statistics(d,c):
    eq=d.equity.to_numpy();r=eq/np.r_[c.initial_cash,eq[:-1]]-1
    dd=eq/np.maximum.accumulate(np.r_[c.initial_cash,eq])[1:]-1
    d['daily_return']=r;d['drawdown']=dd
    years=((pd.Timestamp(c.end)-pd.Timestamp(c.start)).days+1)/365.25
    annual={};last=c.initial_cash
    for y,g in d.groupby(pd.to_datetime(d.date).dt.year):annual[str(y)]=float(g.equity.iloc[-1]/last-1);last=float(g.equity.iloc[-1])
    vol=np.std(r,ddof=1)*np.sqrt(252)
    return dict(ending_equity=float(eq[-1]),net_profit=float(eq[-1]-c.initial_cash),total_return=float(eq[-1]/c.initial_cash-1),cagr=float((eq[-1]/c.initial_cash)**(1/years)-1),max_drawdown=float(dd.min()),annualized_volatility=float(vol),sharpe_zero_rf=float(np.mean(r)*252/vol) if vol else 0,annual_returns=annual)

def benchmark(m,c,full=False):
    dates=m.stock.loc[c.start:c.end].index;first=m.stock.loc[dates[0]];qty=c.initial_cash/float(first.ASK) if full else 100
    cash=c.initial_cash-qty*float(first.ASK);rows=[]
    for i,date in enumerate(dates):
        stockval=qty*float(m.stock.loc[date,'BID']);shares=qty
        if i==len(dates)-1:cash+=stockval;stockval=0;shares=0
        rows.append(dict(date=str(date.date()),equity=cash+stockval,cash=cash,shares=shares,stock_value=stockval))
    d=pd.DataFrame(rows);return d,statistics(d,c)

