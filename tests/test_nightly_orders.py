"""Synthetic inputs verify safety and semantics, never historical performance."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from nightly_orders import generate,clock,build_order,WaitForInput,load,write

class NightlyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        shutil.copytree(ROOT/'schemas',self.root/'schemas')
        shutil.copy(ROOT/'nightly_config.json',self.root)
        self.c=load(self.root/'nightly_config.json')
        self.now=datetime.fromisoformat('2026-11-14T03:00:00+00:00')
        self.prices={'272093':{'tracked':True,'name':'Synthetic test asset','price_history':{'2026-11-13':{'open':520,'high':530,'low':515,'close':523.88}}}}
        write(self.root/'price_history.json',self.prices)
    def tearDown(self):self.temp.cleanup()
    def run_planner(self):return generate(self.root,self.now)
    def test_initial_cash_secured_put(self):
        orders,s=self.run_planner();self.assertEqual(s['status'],'ready')
        o=orders[0];self.assertEqual(o['contract'],'put');self.assertEqual(o['action'],'SHT')
        self.assertEqual(o['for'],'2026-11-16');self.assertLessEqual(o['strike']*100+.65,45000)
        self.assertEqual(o['underlying'],272093);self.assertEqual(o['qty'],1)
    def test_root_mkt_and_site_identical(self):
        self.run_planner()
        self.assertEqual((self.root/'open_orders.json').read_bytes(),(self.root/'mkt/open_orders.json').read_bytes())
        self.assertEqual((self.root/'open_orders.json').read_bytes(),(self.root/'docs/final-cycle/open_orders.json').read_bytes())
    def test_rerun_reuses_id_and_reserves_once(self):
        a,_=self.run_planner();b,_=self.run_planner();self.assertEqual(a,b)
        self.assertEqual(len(load(self.root/'state/order_commitments.json')['orders']),1)
    def test_future_session_waits_for_authoritative_book(self):
        self.run_planner()
        self.prices['272093']['price_history']['2026-11-16']=self.prices['272093']['price_history']['2026-11-13']
        write(self.root/'price_history.json',self.prices)
        self.now=datetime.fromisoformat('2026-11-17T03:00:00+00:00')
        orders,s=self.run_planner();self.assertEqual(len(orders),1);self.assertIn('awaiting_server_book',s['reason'])
        self.assertEqual(orders[0]['for'],'2026-11-16');self.assertEqual(s['active_orders_count'],0)
    def test_stale_prices_keep_prior_dated_ticket_without_retargeting(self):
        self.run_planner();self.now=datetime.fromisoformat('2026-11-18T03:00:00+00:00')
        orders,s=self.run_planner();self.assertEqual(len(orders),1);self.assertIn('stale_prices',s['reason'])
        self.assertEqual(orders[0]['for'],'2026-11-16');self.assertEqual(s['active_orders_count'],0)
        self.assertEqual(s['new_orders_count'],0)
        self.assertEqual(load(self.root/'open_orders.json'),orders)
    def test_one_session_feed_lag_produces_real_dated_paper_ticket(self):
        self.now=datetime.fromisoformat('2026-11-17T03:00:00+00:00')
        orders,s=self.run_planner()
        self.assertEqual(s['status'],'ready');self.assertEqual(s['signal_session'],'2026-11-13')
        self.assertEqual(s['completed_session'],'2026-11-16');self.assertEqual(s['price_lag_sessions'],1)
        self.assertEqual(orders[0]['for'],'2026-11-17');self.assertEqual(orders[0]['strike'],445)
    def test_strict_freshness_can_be_selected(self):
        self.c['max_price_lag_sessions']=0;write(self.root/'nightly_config.json',self.c)
        self.now=datetime.fromisoformat('2026-11-17T03:00:00+00:00')
        orders,s=self.run_planner();self.assertEqual(orders,[]);self.assertIn('stale_prices',s['reason'])
    def test_future_price_does_not_leak(self):
        self.prices['272093']['price_history']['2026-11-16']={'close':999999}
        write(self.root/'price_history.json',self.prices)
        orders,_=self.run_planner();self.assertEqual(orders[0]['strike'],445)
    def test_friday_and_holiday_calendar(self):
        self.assertEqual(clock(datetime.fromisoformat('2026-11-14T03:00:00+00:00')),('2026-11-13','2026-11-16'))
        self.assertEqual(clock(datetime.fromisoformat('2026-11-26T03:00:00+00:00')),('2026-11-25','2026-11-27'))
    def test_early_close(self):
        self.assertEqual(clock(datetime.fromisoformat('2026-11-27T18:30:00+00:00')),('2026-11-27','2026-11-30'))
    def test_dst_calendar(self):
        self.assertEqual(clock(datetime.fromisoformat('2026-07-14T02:00:00+00:00')),('2026-07-13','2026-07-14'))
    def test_during_market_waits(self):
        with self.assertRaises(WaitForInput):clock(datetime.fromisoformat('2026-11-16T16:00:00+00:00'))
    def test_manual_run_during_market_preserves_dated_commitment(self):
        before,_=self.run_planner()
        self.now=datetime.fromisoformat('2026-11-16T16:00:00+00:00')
        orders,s=self.run_planner();self.assertEqual(orders,before)
        self.assertEqual(s['status'],'waiting');self.assertEqual(s['new_orders_count'],0)
        self.assertIn('market_session_in_progress',s['reason'])
    def test_covered_call_respects_all_lot_bases(self):
        b={'cash':1000,'positions':[{'underlying':272093,'contract':'underlying','qty':100,'cost_basis':600}]}
        o=build_order(self.c,523.88,b,'2026-11-16');self.assertEqual(o['contract'],'call');self.assertGreaterEqual(o['strike'],600)
        self.assertLessEqual(o['qty']*100,100)
    def test_short_option_prevents_second_option(self):
        b={'cash':50000,'positions':[{'underlying':272093,'contract':'put','qty':-1}]}
        with self.assertRaises(WaitForInput):build_order(self.c,523.88,b,'2026-11-16')
    def test_insufficient_cash(self):
        with self.assertRaises(WaitForInput):build_order(self.c,523.88,{'cash':100,'positions':[]},'2026-11-16')
    def test_odd_lot_and_missing_basis(self):
        for qty,basis in [(99,600),(100,None),(101,600)]:
            p={'underlying':272093,'contract':'underlying','qty':qty}
            if basis:p['cost_basis']=basis
            with self.assertRaises(WaitForInput):build_order(self.c,523.88,{'cash':1000,'positions':[p]},'2026-11-16')
    def test_malformed_prices_fail_closed(self):
        self.prices['272093']['price_history']['2026-11-13']['close']=-1
        write(self.root/'price_history.json',self.prices)
        orders,s=self.run_planner();self.assertEqual(orders,[]);self.assertEqual(s['status'],'error')
    def test_unknown_position_schema_is_not_guessed(self):
        write(self.root/'mkt/positions.json',{'some_unknown_format':True})
        orders,s=self.run_planner();self.assertEqual(orders,[]);self.assertEqual(s['status'],'error')
    def test_positions_never_modified(self):
        p=self.root/'mkt/positions.json';write(p,{'as_of':'2026-11-13','cash':50000,'positions':[]})
        before=p.read_bytes();self.run_planner();self.assertEqual(p.read_bytes(),before)
    def test_stale_or_conflicting_book_blocks(self):
        p=self.root/'mkt/positions.json';write(p,{'as_of':'2026-11-12','cash':50000,'positions':[]})
        orders,s=self.run_planner();self.assertEqual(orders,[]);self.assertIn('stale_positions',s['reason'])
        write(self.root/'positions.json',{'as_of':'2026-11-13','cash':1,'positions':[]})
        orders,s=self.run_planner();self.assertEqual(orders,[]);self.assertIn('conflicting',s['reason'])
    def test_new_book_allows_next_cycle_without_fake_fills(self):
        self.run_planner()
        self.prices['272093']['price_history']['2026-11-16']=self.prices['272093']['price_history']['2026-11-13']
        write(self.root/'price_history.json',self.prices)
        write(self.root/'mkt/positions.json',{'as_of':'2026-11-16','cash':1000,'positions':[{'underlying':272093,'contract':'underlying','qty':100,'cost_basis':445}]})
        self.now=datetime.fromisoformat('2026-11-17T03:00:00+00:00')
        o,s=self.run_planner();self.assertEqual(o[0]['contract'],'call');self.assertEqual(s['book_source'],'server_positions_adapter')
    def test_order_unknown_field_rejected(self):
        from nightly_orders import validate
        orders,_=self.run_planner();orders[0]['ticker']='MSFT'
        with self.assertRaises(Exception):validate(self.root,'open_orders.schema.json',orders)

if __name__=='__main__':unittest.main()
