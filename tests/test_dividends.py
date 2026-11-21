"""Synthetic fixtures verify entitlement timing, cash and early-assignment stress."""
import unittest
from test_engine import fixture
from comparison_engine import DividendEngine,dividend_benchmark
from backtest import Engine
import pandas as pd

def dividends(ex='2023-01-05',pay='2023-01-09',announcement='2023-01-03',amount=1):
    return pd.DataFrame([dict(ex_date=ex,pay_date=pay,announcement_date=announcement,amount=amount)])
class DividendTests(unittest.TestCase):
    def test_entitlement_then_cash_payment_after_share_delivery(self):
        m,c=fixture();d,e,s=DividendEngine(m,c,'KO.N',dividends()).run()
        self.assertEqual(s['dividends_earned'],100);self.assertEqual(s['dividends_paid'],100)
        self.assertEqual(d.loc[d.date.eq('2023-01-05'),'dividend_receivable'].iloc[0],100)
        self.assertEqual(e.loc[e.action.eq('DIVIDEND_PAID'),'date'].iloc[0],'2023-01-09')
        self.assertEqual(d.dividend_receivable.iloc[-1],0)
    def test_terminal_unpaid_dividend_is_asset_not_spendable_cash(self):
        m,c=fixture();d,e,s=DividendEngine(m,c,'KO.N',dividends(pay='2023-01-20')).run()
        self.assertEqual(s['dividends_paid'],0);self.assertEqual(s['ending_dividend_receivable'],100)
        self.assertAlmostEqual(d.equity.iloc[-1],d.cash.iloc[-1]+100)
    def test_pre_ex_assignment_removes_dividend_entitlement(self):
        m,c=fixture();d,e,s=DividendEngine(m,c,'KO.N',dividends(ex='2023-01-06',amount=2),True).run()
        self.assertEqual(s['pre_dividend_assignments'],1);self.assertEqual(s['dividends_earned'],0)
        self.assertEqual(e.loc[e.action.eq('ASSIGN_CALL'),'date'].iloc[0],'2023-01-05')
    def test_unannounced_dividend_cannot_trigger_prior_assignment(self):
        m,c=fixture();d,e,s=DividendEngine(m,c,'KO.N',dividends(ex='2023-01-06',announcement='2023-01-06',amount=2),True).run()
        self.assertEqual(s['pre_dividend_assignments'],0);self.assertEqual(s['dividends_earned'],200)
    def test_generic_stock_multiplier_is_one(self):
        m,c=fixture();d,e,s=DividendEngine(m,c,'KO.N').run()
        receipt=e.loc[e.action.eq('RECEIVE_SHARES')].iloc[0]
        self.assertEqual(receipt.multiplier,1);self.assertEqual(receipt.cashflow,-9500)
    def test_no_dividend_amzn_parity(self):
        m,c=fixture();d,e,s=Engine(m,c).run();dd,ee,ss=DividendEngine(m,c).run()
        pd.testing.assert_frame_equal(d,dd[d.columns]);pd.testing.assert_frame_equal(e,ee[e.columns])
        for k,v in s.items():self.assertEqual(v,ss[k])
    def test_benchmark_dividend_paid_without_reinvestment(self):
        m,c=fixture();d,e,s=dividend_benchmark(m,c,'KO.N',dividends(),False)
        q=c.initial_cash/float(m.stock.loc['2023-01-03','ASK'])
        self.assertAlmostEqual(s['dividends_earned'],q);self.assertAlmostEqual(s['dividends_paid'],q)
        self.assertAlmostEqual(d.shares.iloc[2],q)
    def test_paid_dividend_reinvests_at_ask_not_ex_date(self):
        m,c=fixture();d,e,s=dividend_benchmark(m,c,'KO.N',dividends(),True)
        reinvest=e.loc[e.action.eq('REINVEST_DIVIDEND')].iloc[0]
        self.assertEqual(reinvest.date,'2023-01-09')
        self.assertEqual(reinvest.price,float(m.stock.loc['2023-01-09','ASK']))
        self.assertGreater(d.loc[d.date.eq('2023-01-09'),'shares'].iloc[0],d.shares.iloc[0])
    def test_stock_bought_on_ex_date_gets_no_dividend(self):
        m,c=fixture();d,e,s=dividend_benchmark(m,c,'KO.N',dividends(ex='2023-01-03'))
        self.assertEqual(s['dividends_earned'],0)
if __name__=='__main__':unittest.main()
