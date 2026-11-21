"""Time-varying, lagged Treasury cash-interest proxy for the revised study.

These are today's historical observations, not a vintage/ALFRED reconstruction.
Only observations strictly before each accrual day may be used. Constant-
maturity yields are an opportunity-cost proxy, not a Treasury total-return index
or a claim about the broker's actual cash-crediting terms.
"""
from pathlib import Path
import math
import numpy as np
import pandas as pd
from comparison_engine import DividendEngine


class TreasuryRates:
    def __init__(self, frame):
        frame = frame.copy()
        frame['observation_date'] = pd.to_datetime(frame.observation_date)
        frame['DGS3MO'] = pd.to_numeric(frame.DGS3MO, errors='coerce') / 100
        self.rates = frame.dropna().set_index('observation_date').DGS3MO.sort_index()
        if self.rates.empty or self.rates.index.has_duplicates:
            raise ValueError('Empty or duplicated Treasury rates')

    @classmethod
    def load(cls, path):
        return cls(pd.read_csv(Path(path)))

    def rate_before(self, day):
        day = pd.Timestamp(day).normalize()
        known = self.rates.loc[self.rates.index < day]
        if known.empty:
            raise ValueError(f'No rate known before {day.date()}')
        if (day-known.index[-1]).days > 10:
            raise ValueError(f'Stale Treasury rate before {day.date()}')
        return float(known.iloc[-1])

    def factor(self, start, end, haircut=0):
        """Accrue (start, end], using ACT/365 and lagged calendar-day rates."""
        start, end = pd.Timestamp(start), pd.Timestamp(end)
        if end < start:
            raise ValueError('Negative accrual interval')
        factor = 1.0
        for day in pd.date_range(start+pd.Timedelta(days=1), end, freq='D'):
            factor *= 1 + max(0, self.rate_before(day)-haircut)/365
        return factor-1


def add_excess_statistics(daily, summary, rates):
    dates = pd.to_datetime(daily.date).tolist()
    rf = np.array([0.] + [rates.factor(a, b) for a,b in zip(dates,dates[1:])])
    excess = daily.daily_return.to_numpy()-rf
    std = np.std(excess, ddof=1)
    daily['risk_free_return'] = rf
    daily['excess_return'] = excess
    summary = dict(summary)
    summary['sharpe_excess_treasury'] = float(np.mean(excess)/std*np.sqrt(252)) if std else 0.
    # Keep the archived metric only under a clear diagnostic name.
    summary['sharpe_zero_rf_archival_diagnostic'] = summary.pop('sharpe_zero_rf')
    summary['risk_free_proxy'] = 'FRED DGS3MO; strictly lagged; ACT/365 calendar-day compounding'
    return summary


class RateAwareWheel(DividendEngine):
    def __init__(self, *args, rates, haircut=0, **kwargs):
        super().__init__(*args, **kwargs)
        if self.c.cash_rate:
            raise ValueError('Do not combine constant and time-varying cash rates')
        self.rates, self.haircut, self.previous_accrual = rates, haircut, None

    def dividend_events(self):
        # This hook runs at the start of each session, before new trades/dividends.
        # self.cash and self.short still describe the previous close's book.
        if self.previous_accrual is not None:
            collateral = 0.
            if self.short:
                meta = self.m.meta.loc[self.short]
                if meta.right == 'P':
                    collateral = 100*self.short_lots*float(meta.strike)
            principal = max(0, self.cash-collateral)
            factor = self.rates.factor(self.previous_accrual, self.date, self.haircut)
            self.event('INTEREST','CASH',0,reason='lagged_treasury_free_cash_proxy',
                       cashflow=principal*factor,interest_principal=principal,
                       interest_factor=factor,accrual_start=str(self.previous_accrual.date()),
                       accrual_end=str(self.date.date()),rate_haircut=self.haircut)
        self.previous_accrual = self.date
        super().dividend_events()

    def run(self):
        d,e,s = super().run()
        s = add_excess_statistics(d,s,self.rates)
        s['interest_earned'] = float(e.loc[e.action.eq('INTEREST'),'cashflow'].sum())
        return d,e,s


def rate_aware_benchmark(m,c,symbol,dividends,rates,reinvest=True,haircut=0):
    """Same fractional-share dividend benchmark, with interest on residual cash."""
    from backtest import statistics
    dates=m.stock.loc[c.start:c.end].index
    cash=c.initial_cash;shares=0.;pending={};events=[];rows=[];earned=0.
    divs=dividends.copy()
    for col in ['ex_date','pay_date','announcement_date']:
        divs[col]=pd.to_datetime(divs[col])
    def event(date,action,instrument,quantity,price,cashflow,**extra):
        nonlocal cash
        cash+=cashflow
        events.append(dict(event_id=len(events)+1,date=str(date.date()),action=action,
            instrument=instrument,quantity=quantity,price=price,fee=0,cashflow=cashflow,
            cash_after=cash,shares_after=shares,
            dividend_receivable_after=sum(x['amount'] for x in pending.values()),**extra))
    for i,date in enumerate(dates):
        if i:
            principal=max(0,cash);factor=rates.factor(dates[i-1],date,haircut)
            event(date,'INTEREST','CASH',0,0,principal*factor,interest_principal=principal,
                  interest_factor=factor,accrual_start=str(dates[i-1].date()),accrual_end=str(date.date()))
        if shares:
            for _,div in divs.loc[divs.ex_date.eq(date)].iterrows():
                key=f'{symbol}:{date.date()}';amount=shares*float(div.amount)
                pending[key]=dict(amount=amount,pay_date=div.pay_date);earned+=amount
                event(date,'DIVIDEND_ENTITLEMENT','CASH',0,0,0,dividend_id=key,
                      dividend_amount=amount,entitled_shares=shares,pay_date=str(div.pay_date.date()))
        for key in [k for k,v in pending.items() if v['pay_date']<=date]:
            x=pending.pop(key);event(date,'DIVIDEND_PAID','CASH',0,0,x['amount'],dividend_id=key)
        if i==0:
            shares=c.initial_cash/float(m.stock.loc[date,'ASK'])
            event(date,'BUY_STOCK',symbol,shares,float(m.stock.loc[date,'ASK']),-c.initial_cash)
        if reinvest and 0<i<len(dates)-1 and cash>1e-8:
            price=float(m.stock.loc[date,'ASK']);qty=cash/price;cost=cash;shares+=qty
            event(date,'REINVEST_CASH',symbol,qty,price,-cost)
        stock_value=shares*float(m.stock.loc[date,'BID'])
        if i==len(dates)-1:
            qty=shares;shares=0.;event(date,'SELL_STOCK',symbol,-qty,float(m.stock.loc[date,'BID']),stock_value);stock_value=0.
        claim=sum(x['amount'] for x in pending.values())
        rows.append(dict(date=str(date.date()),equity=cash+stock_value+claim,cash=cash,
                         shares=shares,stock_value=stock_value,dividend_receivable=claim))
    d=pd.DataFrame(rows);e=pd.DataFrame(events);s=statistics(d,c)
    s.update(dividends_reinvested=reinvest,dividends_earned=earned,
             dividends_paid=float(e.loc[e.action.eq('DIVIDEND_PAID'),'cashflow'].sum()),
             ending_dividend_receivable=float(d.dividend_receivable.iloc[-1]),
             interest_earned=float(e.loc[e.action.eq('INTEREST'),'cashflow'].sum()))
    assert math.isclose(c.initial_cash+e.cashflow.sum(),cash,abs_tol=1e-6)
    assert math.isclose(s['ending_equity'],cash+s['ending_dividend_receivable'],abs_tol=1e-6)
    return d,e,add_excess_statistics(d,s,rates)
