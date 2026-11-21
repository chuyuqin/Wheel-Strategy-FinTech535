"""Cross-stock extension of the frozen wheel: symbols and dividend accounting.
The original backtest.py and its freeze are preserved. No selection rules change.
"""
from dataclasses import replace
from collections import Counter
import math
import pandas as pd
import numpy as np
from backtest import Config,Market,quote_ok,ask_ok,fill,statistics

class DividendEngine:
    def __init__(self,m,c,symbol="AMZN.O",dividends=None,dividend_assignment=False):
        self.symbol=symbol;self.dividend_assignment=dividend_assignment
        self.dividends=dividends.copy() if dividends is not None else pd.DataFrame(columns=["ex_date","pay_date","announcement_date","amount"])
        for col in ["ex_date","pay_date","announcement_date"]:self.dividends[col]=pd.to_datetime(self.dividends[col])
        self.pending_dividends={};self.dividends_earned=0
        self.m=m;self.c=c;self.cash=c.initial_cash;self.shares=0;self.short=None;self.short_lots=0;self.stock_basis=0
        self.events=[];self.daily=[];self.skips=[];self.last_mark=None
        self.date=None;self.signal=None;self.cycle=0;self.open_trade=None
    def event(self,action,instrument,qty,price=0,fee=0,reason='',cashflow=None,**extra):
        mult=1 if instrument in (self.symbol,'CASH') else 100
        cf=-qty*price*mult-fee if cashflow is None else cashflow
        self.cash+=cf
        row=dict(event_id=len(self.events)+1,date=str(self.date.date()),signal_date=str(self.signal.date()),cycle=self.cycle,action=action,instrument=instrument,quantity=qty,multiplier=mult,price=float(price),fee=float(fee),cashflow=float(cf),cash_after=float(self.cash),shares_after=self.shares,short_after=self.short or '',short_contracts_after=self.short_lots,stock_basis_after=self.stock_basis,dividend_receivable_after=self.receivable(),reason=reason)
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
            self.event('RECEIVE_SHARES' if qty>0 else 'DELIVER_SHARES',self.symbol,qty,float(info.strike),reason=reason,option_ric=ric)
            if qty<0:self.cycle+=1
        else:self.event('EXPIRE',ric,lots,reason='expiry_otm',open_event_id=self.open_trade)
    def receivable(self):
        return sum(x['amount'] for x in self.pending_dividends.values())
    def dividend_events(self):
        # Ownership before ex-date trading determines entitlement. Dividend cash
        # is unavailable until the actual pay date (posted next session if closed).
        for _,div in self.dividends.loc[self.dividends.ex_date.eq(self.date)].iterrows():
            if self.shares<=0:continue
            key=f'{self.symbol}:{str(self.date.date())}'
            amount=float(div.amount)*self.shares
            assert key not in self.pending_dividends
            self.pending_dividends[key]=dict(amount=amount,pay_date=div.pay_date)
            self.dividends_earned+=amount
            self.event('DIVIDEND_ENTITLEMENT','CASH',0,reason='ex_date_ownership',cashflow=0,dividend_id=key,dividend_amount=amount,dividend_per_share=float(div.amount),entitled_shares=self.shares,pay_date=str(div.pay_date.date()))
        due=[key for key,x in self.pending_dividends.items() if x['pay_date']<=self.date]
        for key in due:
            x=self.pending_dividends.pop(key)
            self.event('DIVIDEND_PAID','CASH',0,reason='payment_date',cashflow=x['amount'],dividend_id=key,pay_date=str(x['pay_date'].date()))
    def pre_dividend_assignment(self,next_session):
        if self.m.meta.loc[self.short,'right']!='C':return
        known=self.dividends.loc[self.dividends.ex_date.eq(next_session)&self.dividends.announcement_date.le(self.date)]
        if known.empty:return
        q=self.m.quote(self.date,self.short)
        if not quote_ok(q):return
        strike=float(self.m.meta.loc[self.short,'strike']);spot=float(self.m.stock.loc[self.date,'TRDPRC_1'])
        intrinsic=max(0,spot-strike);extrinsic=max(0,float(q.BID)-intrinsic)
        if intrinsic>=.01 and extrinsic<=float(known.amount.sum()):
            self.settle('pre_dividend_assignment')
            for event in self.events[-2:]:event.update(trigger_ex_date=str(next_session.date()),trigger_announcement_date=str(known.announcement_date.max().date()),trigger_dividend=float(known.amount.sum()),trigger_bid_time_value=extrinsic)
    def run(self):
        all_dates=self.m.stock.index;dates=all_dates[(all_dates>=self.c.start)&(all_dates<=self.c.end)]
        previous_date=None
        for step,date in enumerate(dates):
            self.date=date;idx=all_dates.get_loc(date);assert idx>0
            self.signal=all_dates[idx-1];assert self.signal<date
            if previous_date is not None and self.c.cash_rate:
                interest=self.cash*self.c.cash_rate*(date-previous_date).days/365
                self.event('INTEREST','CASH',0,reason='constant_rate_scenario',cashflow=interest)
            self.dividend_events()
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
                    self.event('SELL_STOCK',self.symbol,qty,fill(q,False,self.c),reason='terminal_liquidation')
            elif not self.short and not blocked:self.open()
            if self.short and self.m.meta.loc[self.short,'expiry']<=date:self.settle('expiry_assignment')
            if self.short and self.dividend_assignment and not ending and idx+1<len(all_dates):self.pre_dividend_assignment(all_dates[idx+1])
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
            self.daily.append(dict(date=str(date.date()),cash=self.cash,shares=self.shares,short_contracts=self.short_lots,stock_basis=self.stock_basis,stock_bid=float(sq.BID),stock_close=float(sq.TRDPRC_1),stock_value=stock_value,short_put=self.short if info is not None and info.right=='P' else '',covered_call=self.short if info is not None and info.right=='C' else '',option_strike=float(info.strike) if info is not None else 0,option_expiry=str(info.expiry.date()) if info is not None else '',option_ask=mark,short_liability=liability,reserved_cash=collateral,free_cash=self.cash-collateral,dividend_receivable=self.receivable(),equity=self.cash+stock_value+self.receivable()-liability,carried_mark=int(carried),state='SHORT_PUT' if collateral else ('COVERED_CALL' if self.short else ('SHARES' if self.shares else 'CASH'))))
            previous_date=date
        d=pd.DataFrame(self.daily);e=pd.DataFrame(self.events) if self.events else pd.DataFrame(columns=["date","action","instrument","quantity","price","fee","cashflow"])
        assert not self.short and self.shares==0
        assert math.isclose(self.cash,self.c.initial_cash+e.cashflow.sum(),abs_tol=1e-6)
        d['daily_cashflow']=d.date.map(e.groupby('date').cashflow.sum()).fillna(0)
        assert np.allclose(d.cash,self.c.initial_cash+d.daily_cashflow.cumsum())
        s=statistics(d,self.c)
        s.update(dividends_earned=float(self.dividends_earned),dividends_paid=float(e.loc[e.action.eq('DIVIDEND_PAID'),'cashflow'].sum()),ending_dividend_receivable=float(self.receivable()),pre_dividend_assignments=int(e.reason.eq('pre_dividend_assignment').sum()//2) if 'reason' in e else 0,contracts_sold=int(-e.loc[e.action.eq('SELL_TO_OPEN'),'quantity'].sum()),mean_capital_usage=float(((d.reserved_cash+d.stock_value)/d.equity).mean()),option_opens=int(e.action.eq('SELL_TO_OPEN').sum()),option_closes=int(e.action.eq('BUY_TO_CLOSE').sum()),put_assignments=int(e.action.eq('ASSIGN_PUT').sum()),call_assignments=int(e.action.eq('ASSIGN_CALL').sum()),expirations=int(e.action.eq('EXPIRE').sum()),fees=float(e.fee.sum()),premium_received=float((-e.loc[e.action.eq('SELL_TO_OPEN'),'quantity']*e.loc[e.action.eq('SELL_TO_OPEN'),'price']).sum()*100),buyback_cost=float((e.loc[e.action.eq('BUY_TO_CLOSE'),'quantity']*e.loc[e.action.eq('BUY_TO_CLOSE'),'price']).sum()*100),stock_cashflow=float(e.loc[e.instrument.eq(self.symbol),'cashflow'].sum()),carried_mark_days=int(d.carried_mark.sum()),skip_reasons=dict(Counter(x['reason'] for x in self.skips)),stock_exposure_fraction=float(d.shares.gt(0).mean()),mean_reserved_cash=float(d.reserved_cash.mean()),events=len(e))
        assert math.isclose(s['net_profit'],s['premium_received']-s['buyback_cost']+s['stock_cashflow']-s['fees']+float(e.loc[e.action.isin(['INTEREST','DIVIDEND_PAID']),'cashflow'].sum())+self.receivable(),abs_tol=1e-6)
        return d,e,s

def dividend_benchmark(m,c,symbol,dividends,reinvest=True):
    """Fractional shares; paid dividends reinvest at ask unless disabled explicitly."""
    dates=m.stock.loc[c.start:c.end].index
    qty=c.initial_cash/float(m.stock.loc[dates[0],'ASK']);cash=c.initial_cash;shares=0;pending={};events=[];rows=[];earned=0
    divs=dividends.copy()
    for col in ['ex_date','pay_date','announcement_date']:divs[col]=pd.to_datetime(divs[col])
    def event(date,action,instrument,quantity,price,cashflow,**extra):
        nonlocal cash
        cash+=cashflow
        events.append(dict(event_id=len(events)+1,date=str(date.date()),action=action,instrument=instrument,quantity=quantity,price=price,fee=0,cashflow=cashflow,cash_after=cash,shares_after=shares,dividend_receivable_after=sum(x['amount'] for x in pending.values()),**extra))
    for i,date in enumerate(dates):
        # Existing ownership, before any execution at this close.
        if shares:
            for _,div in divs.loc[divs.ex_date.eq(date)].iterrows():
                key=f'{symbol}:{date.date()}';amount=shares*float(div.amount);pending[key]=dict(amount=amount,pay_date=div.pay_date);earned+=amount
                event(date,'DIVIDEND_ENTITLEMENT','CASH',0,0,0,dividend_id=key,dividend_amount=amount,entitled_shares=shares,pay_date=str(div.pay_date.date()))
        for key in [k for k,v in pending.items() if v['pay_date']<=date]:
            x=pending.pop(key);event(date,'DIVIDEND_PAID','CASH',0,0,x['amount'],dividend_id=key,pay_date=str(x['pay_date'].date()))
        if i==0:
            shares=qty;event(date,'BUY_STOCK',symbol,qty,float(m.stock.loc[date,'ASK']),-c.initial_cash)
        if reinvest and i>0 and i<len(dates)-1 and cash>1e-8:
            price=float(m.stock.loc[date,'ASK']);extra_shares=cash/price;cost=cash;shares+=extra_shares
            event(date,'REINVEST_DIVIDEND',symbol,extra_shares,price,-cost)
        stock_value=shares*float(m.stock.loc[date,'BID'])
        if i==len(dates)-1:
            quantity_to_sell=shares;shares=0;event(date,'SELL_STOCK',symbol,-quantity_to_sell,float(m.stock.loc[date,'BID']),stock_value);stock_value=0
        claim=sum(x['amount'] for x in pending.values())
        rows.append(dict(date=str(date.date()),equity=cash+stock_value+claim,cash=cash,shares=shares,stock_value=stock_value,dividend_receivable=claim))
    d=pd.DataFrame(rows);e=pd.DataFrame(events);s=statistics(d,c)
    s.update(dividends_reinvested=reinvest,dividends_earned=earned,dividends_paid=float(e.loc[e.action.eq('DIVIDEND_PAID'),'cashflow'].sum()),ending_dividend_receivable=float(d.dividend_receivable.iloc[-1]))
    assert math.isclose(c.initial_cash+e.cashflow.sum(),cash,abs_tol=1e-6)
    assert math.isclose(s['ending_equity'],cash+s['ending_dividend_receivable'],abs_tol=1e-6)
    return d,e,s
