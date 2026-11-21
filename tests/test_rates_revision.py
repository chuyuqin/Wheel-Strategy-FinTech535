"""Small synthetic accounting fixtures; none supply study performance."""
import sys
import unittest
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from backtest import Config
from rates_revision import TreasuryRates,RateAwareWheel,add_excess_statistics


class RatesTests(unittest.TestCase):
    def setUp(self):
        self.rates=TreasuryRates(pd.DataFrame({'observation_date':['2024-01-04','2024-01-05','2024-01-08'],'DGS3MO':[5,6,99]}))

    def test_no_same_day_rate(self):
        self.assertAlmostEqual(self.rates.rate_before('2024-01-08'),.06)
        self.assertAlmostEqual(self.rates.rate_before('2024-01-09'),.99)

    def test_weekend_gets_three_calendar_days(self):
        self.assertAlmostEqual(self.rates.factor('2024-01-05','2024-01-08'),(1+.06/365)**3-1)

    def test_missing_history_fails(self):
        with self.assertRaises(ValueError):self.rates.rate_before('2024-01-04')

    def test_stale_history_fails(self):
        with self.assertRaises(ValueError):self.rates.rate_before('2024-02-01')

    def test_haircut_is_rate_difference_not_percentage_multiplier(self):
        self.assertAlmostEqual(self.rates.factor('2024-01-05','2024-01-06',.01),.05/365)

    def test_no_negative_cash_credit(self):
        self.assertEqual(self.rates.factor('2024-01-05','2024-01-06',.10),0)

    def test_negative_interval_fails(self):
        with self.assertRaises(ValueError):self.rates.factor('2024-01-08','2024-01-05')

    def test_reserved_put_cash_never_earns_interest(self):
        market=SimpleNamespace(meta=pd.DataFrame([dict(ric='put',right='P',strike=100)]).set_index('ric'))
        wheel=RateAwareWheel(market,Config(initial_cash=25000),rates=self.rates)
        wheel.previous_accrual=pd.Timestamp('2024-01-05');wheel.date=pd.Timestamp('2024-01-08');wheel.signal=pd.Timestamp('2024-01-05')
        wheel.cash=25000;wheel.short='put';wheel.short_lots=2
        # Set a non-spendable dividend receivable: it must not earn interest.
        wheel.pending_dividends={'claim':dict(amount=1000,pay_date=pd.Timestamp('2024-02-01'))}
        wheel.dividend_events()
        e=wheel.events[0]
        self.assertEqual(e['interest_principal'],5000)
        self.assertAlmostEqual(e['cashflow'],5000*((1+.06/365)**3-1))

    def test_risk_free_interval_matches_account_weekend_return(self):
        factor=self.rates.factor('2024-01-05','2024-01-08')
        d=pd.DataFrame({'date':['2024-01-05','2024-01-08'],'daily_return':[0,factor]})
        s=add_excess_statistics(d,{'sharpe_zero_rf':1},self.rates)
        self.assertAlmostEqual(d.excess_return.abs().sum(),0)
        self.assertEqual(s['sharpe_excess_treasury'],0)

    def test_constant_and_varying_rates_cannot_double_count(self):
        with self.assertRaises(ValueError):
            RateAwareWheel(SimpleNamespace(),Config(cash_rate=.05),rates=self.rates)


if __name__=='__main__':unittest.main()
