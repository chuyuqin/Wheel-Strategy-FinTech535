"""Small synthetic fixtures test accounting only, never reported performance."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from backtest import *
def fixture():
    dates=pd.to_datetime(['2023-01-02','2023-01-03','2023-01-04','2023-01-05','2023-01-06','2023-01-09','2023-01-10'])
    prices=[100,100,90,100,110,110,110]
    stock=pd.DataFrame({'BID':prices,'ASK':np.array(prices)+.02,'TRDPRC_1':prices},index=dates)
    rows=[]
    for i,date in enumerate(dates):
        for ric,right,exp,k in [('PUT','P','2023-01-04',95),('CALL','C','2023-01-06',95)]:
            if date>pd.Timestamp(exp):continue
            intrinsic=max(0,k-prices[i] if right=='P' else prices[i]-k)
            rows.append(dict(date=date,ric=ric,right=right,expiry=exp,strike=k,BID=intrinsic+1,ASK=intrinsic+1.2,DELTA=-.3 if right=='P' else .3,ACVOL_UNS=100,OPINT_1=1000))
    c=Config(start='2023-01-03',end='2023-01-10',dte_min=1,dte_max=5,dte_target=2,max_relative_spread=.5)
    return Market(stock,pd.DataFrame(rows)),c
class EngineTests(unittest.TestCase):
    def test_physical_wheel_and_cash_conservation(self):
        m,c=fixture();d,e,s=Engine(m,c).run()
        self.assertEqual(s['put_assignments'],1);self.assertEqual(s['call_assignments'],1)
        self.assertEqual(list(e.loc[e.instrument.eq('AMZN.O'),'quantity']),[100,-100])
        self.assertAlmostEqual(d.equity.iloc[-1],c.initial_cash+e.cashflow.sum())
        self.assertTrue(np.allclose(d.equity,d.cash+d.stock_value-d.short_liability))
    def test_collateral_and_share_cover(self):
        m,c=fixture();d,e,s=Engine(m,c).run()
        self.assertTrue((d.cash>=d.reserved_cash).all())
        self.assertTrue((d.loc[d.covered_call.ne(''),'shares']==100).all())
        self.assertTrue((pd.to_datetime(e.signal_date)<pd.to_datetime(e.date)).all())
    def test_no_substitution_after_bad_execution_quote(self):
        m,c=fixture();m.chains[pd.Timestamp('2023-01-03')].loc['PUT','ASK']=.5
        d,e,s=Engine(m,c).run()
        self.assertFalse(((e.date=='2023-01-03')&(e.action=='SELL_TO_OPEN')).any())
    def test_missing_mark_fails(self):
        m,c=fixture();m.meta.loc['PUT','expiry']=pd.Timestamp('2023-01-06')
        m.chains[pd.Timestamp('2023-01-04')].loc['PUT','ASK']=np.nan
        with self.assertRaises(ValueError):Engine(m,replace(c,max_carried_sessions=0)).run()
    def test_cash_constraint_blocks_put(self):
        m,c=fixture();d,e,s=Engine(m,replace(c,initial_cash=1000)).run()
        self.assertTrue(e.empty if e.empty else not e.action.eq('SELL_TO_OPEN').any())
    def test_terminal_close_uses_ask(self):
        m,c=fixture();d,e,s=Engine(m,replace(c,end='2023-01-04',roll_dte=0)).run()
        close=e.loc[e.action.eq('BUY_TO_CLOSE')].iloc[0]
        self.assertAlmostEqual(close.price,6.2);self.assertEqual(close.reason,'terminal_liquidation')
    def test_spread_stress_reduces_fill(self):
        m,c=fixture();q=m.quote(pd.Timestamp('2023-01-03'),'PUT')
        self.assertAlmostEqual(fill(q,False,replace(c,extra_spread_fraction=.5)),.9)
    def test_expiry_otm_no_share_transfer(self):
        m,c=fixture();m.stock.loc[pd.Timestamp('2023-01-04'),['BID','TRDPRC_1','ASK']]=[100,100,100.02]
        d,e,s=Engine(m,c).run();self.assertEqual(s['put_assignments'],0)
        self.assertTrue(e.action.eq('EXPIRE').any())
class RevisedPolicyTests(unittest.TestCase):
    def test_multi_contract_physical_transfers(self):
        m,c=fixture();d,e,s=Engine(m,replace(c,allocation_fraction=.9)).run()
        self.assertEqual(e.loc[e.action.eq('SELL_TO_OPEN'),'quantity'].iloc[0],-4)
        self.assertEqual(list(e.loc[e.instrument.eq('AMZN.O'),'quantity']),[400,-400])
        self.assertAlmostEqual(s['net_profit'],s['premium_received']-s['buyback_cost']+s['stock_cashflow']-s['fees'])
        self.assertTrue((d.cash>=d.reserved_cash).all())
    def test_cost_floor_blocks_sale_below_purchase_price(self):
        m,c=fixture()
        m.meta.loc['CALL','strike']=94
        for chain in m.chains.values():
            if 'CALL' in chain.index:chain.loc['CALL','strike']=94
        d,e,s=Engine(m,replace(c,call_cost_floor=True)).run()
        self.assertFalse(((e.action=='SELL_TO_OPEN')&(e.instrument=='CALL')).any())
        self.assertEqual(s['call_assignments'],0)
    def test_future_prices_cannot_change_earlier_fills(self):
        m,c=fixture();a,ae,_=Engine(m,c).run()
        m2,c2=fixture();m2.stock.loc[pd.Timestamp('2023-01-09'),['BID','ASK','TRDPRC_1']]=[200,200.02,200]
        b,be,_=Engine(m2,c2).run()
        pd.testing.assert_frame_equal(a.loc[a.date<'2023-01-09'].reset_index(drop=True),b.loc[b.date<'2023-01-09'].reset_index(drop=True))
        pd.testing.assert_frame_equal(ae.loc[ae.date<'2023-01-09'].reset_index(drop=True),be.loc[be.date<'2023-01-09'].reset_index(drop=True))
    def test_opening_contract_count_cannot_use_received_premium(self):
        m,c=fixture();d,e,s=Engine(m,replace(c,initial_cash=10000,allocation_fraction=.9)).run()
        self.assertFalse(e.action.eq('SELL_TO_OPEN').any())
if __name__=='__main__':unittest.main()
