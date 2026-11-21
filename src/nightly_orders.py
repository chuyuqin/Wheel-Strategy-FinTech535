"""Nightly educational wheel order planner. No broker calls or simulated fills.

The initial paper budget is used once. After issuing an order, wait for an
authoritative, current book before issuing another session's commitment.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import hashlib
import json
import math
import os
from pathlib import Path
import sys

import exchange_calendars as xcals
import pandas as pd
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]
NY = 'America/New_York'

class WaitForInput(ValueError):
    pass

def load(path):
    return json.loads(path.read_text())

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temp.replace(path)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

def validate(root, name, value):
    Draft202012Validator(load(root/'schemas'/name), format_checker=FormatChecker()).validate(value)

def clock(now):
    stamp = pd.Timestamp(now)
    if stamp.tzinfo is None:
        raise ValueError('A timezone-aware clock is required')
    day = stamp.tz_convert(NY).date()
    cal = xcals.get_calendar('XNYS',start=str(day-pd.Timedelta(days=30)),end=str(day+pd.Timedelta(days=30)))
    sessions = cal.sessions_in_range(str(day-pd.Timedelta(days=14)), str(day+pd.Timedelta(days=14)))
    completed = [s for s in sessions if cal.session_close(s) <= stamp]
    upcoming = [s for s in sessions if cal.session_open(s) > stamp]
    if not completed or not upcoming:
        raise ValueError('No market sessions available around the run clock')
    latest = completed[-1]
    target = upcoming[0]
    if cal.is_session(str(day)) and cal.session_open(str(day)) <= stamp < cal.session_close(str(day)):
        raise WaitForInput('market_session_in_progress: run after the close')
    return str(latest.date()), str(target.date())

def validate_config(c):
    if type(c['max_price_lag_sessions']) is not int or not 0 <= c['max_price_lag_sessions'] <= 1:
        raise ValueError('Price lag must be zero or one completed session')
    if type(c['underlying']) is not int or c['underlying'] <= 0:
        raise ValueError('underlying must be a positive integer conid')
    for key in ['paper_initial_cash','strike_increment','option_fee_reserve']:
        if not math.isfinite(c[key]) or c[key] <= 0:
            raise ValueError('invalid '+key)
    if not (0 < c['allocation_fraction'] <= 1 and 0 < c['minimum_put_moneyness'] < c['put_moneyness'] < 1 < c['call_moneyness']):
        raise ValueError('Invalid allocation or moneyness')
    if c['max_contracts'] != 1 or c['expiry'] != '21DTE+' or not 0 < c['minimum_premium_fraction'] < 1:
        raise ValueError('Unsupported configuration')

def price_input(root, c, expected):
    path = root/'price_history.json'
    if not path.exists(): raise WaitForInput('missing_price_history')
    asset = load(path).get(str(c['underlying']))
    if not asset or asset.get('tracked') is not True:
        raise WaitForInput('configured_conid_not_tracked')
    bars = asset.get('price_history', {})
    # The course feed can lag. Use only a known, completed session, with a
    # bounded one-session tolerance; never manufacture the missing daily bar.
    latest = max((d for d in bars if d <= expected), default=None)
    if latest is None: raise WaitForInput('no_completed_price_bar')
    pd.Timestamp(latest)  # Reject malformed session keys rather than guessing.
    cal = xcals.get_calendar('XNYS',start=str((pd.Timestamp(latest)-pd.Timedelta(days=7)).date()),end=str((pd.Timestamp(expected)+pd.Timedelta(days=7)).date()))
    if not cal.is_session(latest): raise ValueError('Price date is not an NYSE session')
    lag = len(cal.sessions_in_range(latest,expected))-1
    if lag > c['max_price_lag_sessions']:
        raise WaitForInput(f'stale_prices: latest {latest} is {lag} sessions behind {expected}; maximum allowed {c["max_price_lag_sessions"]}')
    bar = bars[latest]
    for key in ('open','high','low','close'):
        if type(bar.get(key)) not in (int,float) or not math.isfinite(bar[key]) or bar[key] <= 0:
            raise ValueError('Invalid price bar')
    if not bar['low'] <= min(bar['open'],bar['close']) <= max(bar['open'],bar['close']) <= bar['high']:
        raise ValueError('Inconsistent OHLC bar')
    return float(bar['close']), asset.get('name', str(c['underlying'])), latest, lag

def book_input(root, c, expected, ledger):
    paths = [p for p in (root/'mkt/positions.json',root/'positions.json') if p.exists()]
    if len(paths) == 2 and load(paths[0]) != load(paths[1]):
        raise WaitForInput('conflicting_positions_files')
    if not paths:
        if ledger['orders']:
            raise WaitForInput('awaiting_server_book: a prior paper commitment is still reserved')
        return dict(as_of=expected,cash=c['paper_initial_cash'],positions=[]), 'initial_paper_budget'
    book = load(paths[0])
    validate(root,'positions-input.schema.json',book)
    if book['as_of'] != expected:
        raise WaitForInput('stale_positions: book must match the completed market session')
    if any(p['underlying'] != c['underlying'] and p['qty'] != 0 for p in book['positions']):
        raise WaitForInput('other_asset_exposure: cannot establish portfolio-wide collateral')
    if any(o['for'] > book['as_of'] for o in ledger['orders']):
        raise WaitForInput('pending_commitment_not_yet_resolved_in_book')
    return book, 'server_positions_adapter'

def build_order(c, close, book, target):
    positions = [p for p in book['positions'] if p['underlying'] == c['underlying'] and p['qty']]
    if any(p['contract'] in ('put','call') for p in positions):
        raise WaitForInput('existing_option: hold to expiry; no overlapping option series')
    stocks = [p for p in positions if p['contract'] == 'underlying']
    shares = sum(p['qty'] for p in stocks)
    if shares < 0: raise WaitForInput('short_stock_not_supported')
    step = Decimal(str(c['strike_increment']))
    if shares:
        if shares < 100 or shares % 100:
            raise WaitForInput('shares_not_whole_covered_call_lots')
        if any('cost_basis' not in p for p in stocks):
            raise WaitForInput('missing_stock_cost_basis')
        # Use the highest lot basis to protect every share lot's gross basis.
        minimum = max(close*c['call_moneyness'],max(p['cost_basis'] for p in stocks))
        strike = float((Decimal(str(minimum))/step).to_integral_value(rounding=ROUND_UP)*step)
        right = 'call'
        if book['cash'] < c['option_fee_reserve']:
            raise WaitForInput('insufficient_fee_cash')
    else:
        budget = book['cash']*c['allocation_fraction'] - c['option_fee_reserve']
        maximum = min(close*c['put_moneyness'],budget/100)
        strike = float((Decimal(str(maximum))/step).to_integral_value(rounding=ROUND_DOWN)*step)
        if strike <= 0 or strike < close*c['minimum_put_moneyness']:
            raise WaitForInput('insufficient_cash_for_reasonable_cash_secured_put')
        right = 'put'
        if strike*100 + c['option_fee_reserve'] > book['cash']*c['allocation_fraction']:
            raise ValueError('Collateral invariant violated')
    premium = float(Decimal(str(max(.01,close*c['minimum_premium_fraction']))).quantize(Decimal('.01'),rounding=ROUND_UP))
    payload = dict(for_session=target,contract=right,strike=strike,premium=premium,conid=c['underlying'],version=c['strategy_version'])
    suffix = hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()[:10]
    return {'id':f"{c['strategy_version']}-{c['underlying']}-{target}-{right}-{suffix}",
            'for':target,'order_type':'lmt','action':'SHT','qty':1,
            'underlying':c['underlying'],'contract':right,'expiry':c['expiry'],
            'strike':strike,'ref':'prev_close','lmt_prc':premium}

def generate(root=ROOT, now=None):
    now = now or datetime.now(timezone.utc)
    report = dict(generated_at=now.isoformat(),status='waiting',orders_count=0,
                  strategy='wheel-final-v1',paper_only=True,broker_connected=False,
                  execution_context='github_actions' if os.environ.get('GITHUB_ACTIONS')=='true' else 'local',
                  price_sha256=digest(root/'price_history.json'))
    if os.environ.get('GITHUB_ACTIONS')=='true':
        report['workflow_run_url'] = f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    orders = []
    ledger = None
    ledger_validated = False
    try:
        c = load(root/'nightly_config.json'); validate_config(c)
        ledger_path = root/'state/order_commitments.json'
        ledger = load(ledger_path) if ledger_path.exists() else {'version':1,'orders':[]}
        if ledger.get('version') != 1 or not isinstance(ledger.get('orders'),list):
            raise ValueError('Invalid commitment ledger')
        validate(root,'open_orders.schema.json',ledger['orders'])
        if len({o['id'] for o in ledger['orders']}) != len(ledger['orders']):
            raise ValueError('Duplicate commitment ids')
        ledger_validated = True
        expected, target = clock(now)
        report.update(completed_session=expected,target_session=target,underlying=c['underlying'])
        close, name, signal, lag = price_input(root,c,expected)
        report.update(asset_name=name,signal_session=signal,price_lag_sessions=lag,
                      max_price_lag_sessions=c['max_price_lag_sessions'])
        same = [o for o in ledger['orders'] if o['for'] == target]
        if same:
            if len(same) != 1: raise ValueError('More than one commitment for this session')
            orders = same
            report.update(status='ready',reason='same_session_commitment_reused',book_source='committed_order')
        else:
            book, source = book_input(root,c,expected,ledger)
            order = build_order(c,close,book,target)
            orders = [order]
            report.update(status='ready',reason='new_wheel_commitment',book_source=source,
                          new_orders_count=1,
                          reserved_cash=order['strike']*100+c['option_fee_reserve'] if order['contract']=='put' else c['option_fee_reserve'],
                          reserved_shares=100 if order['contract']=='call' else 0)
            ledger['orders'].append(order)
            validate(root,'open_orders.schema.json',orders)
            # Reserve before publishing the ticket; a crash can withhold a ticket,
            # but a retry will recover the same id rather than double-allocate.
            write(ledger_path,ledger)
        validate(root,'open_orders.schema.json',orders)
        report['orders_count'] = len(orders)
    except WaitForInput as exc:
        report['reason'] = str(exc)
        # Sanji explicitly permits old dated tickets in the file. Retain the
        # audit trail, without retargeting or assuming any ticket was filled.
        if ledger_validated:
            orders = ledger['orders']
    except ValidationError:
        report.update(status='error',reason='schema_validation_failed: input or order does not match the documented contract')
        orders = []
    except Exception as exc:
        try:
            message = str(exc)
        except Exception:
            message = 'Input/calendar validation failed'
        report.update(status='error',reason=f'{type(exc).__name__}: {message}')
        orders = []
    report['orders_count'] = len(orders)
    report.setdefault('new_orders_count',0)
    report['active_orders_count'] = sum(o['for']==report.get('target_session') for o in orders)
    report['orders_sha256'] = hashlib.sha256((json.dumps(orders,indent=2,allow_nan=False)+'\n').encode()).hexdigest()
    for path in ('open_orders.json','mkt/open_orders.json','docs/final-cycle/open_orders.json'):
        write(root/path,orders)
    write(root/'docs/final-cycle/status.json',report)
    return orders, report

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    args = parser.parse_args()
    orders,report = generate(args.root)
    print(json.dumps(report,indent=2))
    sys.exit(1 if report['status']=='error' else 0)
