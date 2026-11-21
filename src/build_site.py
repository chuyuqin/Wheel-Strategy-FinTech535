"""Build the short class report and its complete audit/source download."""
from pathlib import Path
from datetime import datetime,timezone
import json,re,zipfile,hashlib
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/results'
def money(x):return ('−' if x<0 else '')+f'${abs(x):,.2f}'
def pct(x):return f'{x*100:.2f}%'
def pp(x):return f'{x*100:+.2f} pp'
def tr(values,cls=''):return '<tr'+(' class="'+cls+'"' if cls else '')+'>'+''.join('<td>'+str(x)+'</td>' for x in values)+'</tr>'
def read(p):return json.loads(p.read_text())
def csv(p):return json.loads(pd.read_csv(p).to_json(orient='records'))
def finding(r,key):
    w,b=r['wheel'],r['buy_hold'];text=f"The wheel returned {pct(w['total_return'])}, versus {pct(b['total_return'])} for buy-and-hold: {pp(r['excess_return'])}. "
    if key=='historical':
        text+=f"It was profitable and had a higher zero-rate Sharpe ({w['sharpe_zero_rf']:.2f} versus {b['sharpe_zero_rf']:.2f}), while missing part of the strong 2023–2024 rally. In the continuing account, its 2025 return was {pct(w['annual_returns']['2025'])} versus {pct(b['annual_returns']['2025'])}."
    else:text+=f"The wheel’s largest decline was {pct(w['max_drawdown'])}; buy-and-hold’s was {pct(b['max_drawdown'])}. This period {'favors' if r['excess_return']>0 else 'does not favor'} the wheel on total return."
    return text

def example(periods):
    # First completed cycle in the new test, otherwise the first historical one.
    for key in ['test','historical']:
        events=pd.read_csv(OUT/'selected'/key/'blotter.csv').fillna('')
        calls=events.loc[events.action.eq('ASSIGN_CALL')]
        if calls.empty:continue
        assigned_call=calls.iloc[0];call_open=events.loc[events.event_id.eq(int(assigned_call.open_event_id))].iloc[0]
        puts=events.loc[(events.action=='ASSIGN_PUT')&(events.event_id<call_open.event_id)]
        if puts.empty:continue
        assigned_put=puts.iloc[-1];put_open=events.loc[events.event_id.eq(int(assigned_put.open_event_id))].iloc[0]
        receive=events.loc[(events.action=='RECEIVE_SHARES')&(events.date==assigned_put.date)].iloc[0]
        deliver=events.loc[(events.action=='DELIVER_SHARES')&(events.date==assigned_call.date)].iloc[0]
        cycle=events.loc[events.event_id.between(put_open.event_id,deliver.event_id)]
        rows=''.join(tr([e.date,label,terms,money(e.cashflow)]) for e,label,terms in [(put_open,'Sell cash-secured puts',f'{int(-put_open.quantity)} contracts · strike {money(put_open.strike)} · premium {money(put_open.price)} / share'),(receive,'Put assigned: buy shares',f'{int(receive.quantity)} shares at {money(receive.price)}'),(call_open,'Sell covered calls',f'{int(-call_open.quantity)} contracts · strike {money(call_open.strike)} · premium {money(call_open.price)} / share'),(deliver,'Call assigned: deliver shares',f'{int(-deliver.quantity)} shares at {money(deliver.price)}')])
        premium=-(cycle.loc[cycle.action=='SELL_TO_OPEN','quantity']*cycle.loc[cycle.action=='SELL_TO_OPEN','price']*100).sum();fees=cycle.fee.sum();stock=cycle.loc[cycle.instrument=='AMZN.O','cashflow'].sum();closes=(cycle.loc[cycle.action=='BUY_TO_CLOSE','quantity']*cycle.loc[cycle.action=='BUY_TO_CLOSE','price']*100).sum();net=cycle.cashflow.sum()
        return dict(example_period=periods[key]['label'],example_intro='The first completed put-to-call cycle in this period is shown, rather than the most profitable cycle. The four rows show its entry, assignment, covered-call sale, and delivery.',example_rows=rows,example_result=f"Cycle net cash profit: {money(net)} = {money(premium)} option premiums + {money(stock)} stock cash flows − {money(closes)} buybacks − {money(fees)} commissions. All {int(cycle.action.eq('SELL_TO_OPEN').sum())} option sales between the put entry and share delivery are included; any intervening expirations are in the full blotter.",example_facts=dict(period=key,start=put_open.date,end=deliver.date,net_profit=float(net),premium=float(premium),stock_cashflow=float(stock),fees=float(fees),shares=int(receive.quantity),put_strike=float(put_open.strike),call_strike=float(call_open.strike)))
    raise ValueError('No completed cycle exists to illustrate')

def main():
    if (ROOT/'src/amzn_app.js').exists():
        (ROOT/'docs/assets/app.js').write_text((ROOT/'src/amzn_app.js').read_text())
    periods=read(OUT/'periods.json');freeze=read(OUT/'frozen_strategy.json');study=read(OUT/'parameter_study.json');audit=read(OUT/'data_audit.json');fresh=read(OUT/'test_data_audit.json');verification=read(OUT/'verification.json');stress=read(OUT/'stress_tests.json');c=freeze['config'];default='historical';r=periods[default];w=r['wheel'];b=r['buy_hold']
    notes={'historical':'Retrospective 2023–2025 study. Parameters were selected using 2023; the full-period result is not wholly out of sample.','training':'2023 selected the parameters. These are training results.','validation':'2024 is chronological validation. Its prices had been examined in the earlier baseline study.','diagnostic':'2025 is a previously seen diagnostic, not an untouched holdout.','test':'January 2 – October 30, 2026. Data were downloaded after the rule freeze; the selected parameters were not changed.'}
    payload={}
    for key,s in periods.items():payload[key]=dict(summary=s,note=notes[key],finding=finding(s,key),daily=csv(OUT/'selected'/key/'daily.csv'),events=csv(OUT/'selected'/key/'blotter.csv'),benchmark=csv(OUT/'selected'/key/'benchmark_daily.csv'))
    opts=''.join(f'<option value="{key}"'+(' selected' if key==default else '')+'>'+periods[key]['label']+'</option>' for key in ['historical','test','training','validation','diagnostic'])
    params=''.join(tr([f"{int(x['config']['put_delta']*100)} / {int(x['config']['call_delta']*100)} delta · {x['config']['dte_target']} days"+(' · selected' if x['id']==freeze['selected_id'] else ''),pct(x['training']['wheel']['total_return']),pct(x['validation']['wheel']['total_return']),pct(x['diagnostic']['wheel']['total_return'])],'parameter-selected' if x['id']==freeze['selected_id'] else '') for x in study)
    annual=''.join(tr([year,pct(w['annual_returns'][year]),pct(b['annual_returns'][year]),pp(w['annual_returns'][year]-b['annual_returns'][year])]) for year in w['annual_returns'])
    prows=''.join(tr([periods[key]['label'],pct(periods[key]['wheel']['total_return']),pct(periods[key]['buy_hold']['total_return']),pp(periods[key]['excess_return'])]) for key in ['training','validation','diagnostic','test'])
    comparison=''.join(tr([label,money(s['ending_equity']),pct(s['cagr']),pct(s['annualized_volatility']),f"{s['sharpe_zero_rf']:.2f}",pct(s['max_drawdown'])]) for label,s in [('Wheel',w),('Fully invested AMZN',b)])
    srows=tr(['Baseline',pct(periods['test']['wheel']['total_return']),pct(periods['test']['wheel']['max_drawdown'])])+''.join(tr([f'<a href="results/stress/{s["label"].lower().replace(" ","_")}/blotter.csv">{s["label"]}</a>',pct(s['wheel']['total_return']),pct(s['wheel']['max_drawdown'])]) for s in stress)
    ev=pd.read_csv(OUT/'selected/historical/blotter.csv');opens=ev.loc[ev.action=='SELL_TO_OPEN'];spreads=opens.ask-opens.bid;midcost=(-opens.quantity*spreads*50).sum()
    ex=example(periods)
    vals=dict(put_delta=round(c['put_delta']*100),call_delta=round(c['call_delta']*100),target_dte=c['dte_target'],parameter_rows=params,period_options=opts,period_note=notes[default],wheel_return=pct(w['total_return']),wheel_equity=money(w['ending_equity'])+' ending equity',bh_return=pct(b['total_return']),excess_return=pp(r['excess_return']),max_drawdown=pct(w['max_drawdown']),bh_drawdown='Buy-and-hold '+pct(b['max_drawdown']),result_finding=finding(r,default),annual_rows=annual,period_rows=prows,comparison_rows=comparison,stress_rows=srows,fill_evidence=f"For the continuing 2023–2025 account, the median opening spread was {money(spreads.median())} per share and the 90th percentile was {money(spreads.quantile(.9))}. Selling at bid rather than midpoint reduced receipts by {money(midcost)} across {w['contracts_sold']} contracts. Observed activity and spreads justify charging a measurable execution cost; daily quotes do not guarantee fill freshness or depth.",audit_text=f"LSEG supplies {audit['option_day_records']:,} normalized option-day observations for the earlier sample and {fresh['option_day_records']:,} for the 2026 sample. All {verification['raw_responses_verified']} response checksums passed. Independent replays reconciled {verification['events_replayed']:,} events and {verification['daily_portfolios_reconciled']:,} daily portfolios across all selected, parameter, and stress runs. {verification['unit_tests']} engine tests passed. The selected full-period and 2026 runs use {w['carried_mark_days']} and {periods['test']['wheel']['carried_mark_days']} carried-mark sessions respectively.",**{k:v for k,v in ex.items() if k!='example_facts'})
    page=(ROOT/'src/page.html').read_text()
    for k,v in vals.items():page=page.replace('{{'+k+'}}',str(v))
    assert not re.search(r'\{\{\w+\}\}',page)
    (ROOT/'docs/index.html').write_text(page);(ROOT/'docs/assets/data.js').write_text('window.WHEEL_DATA='+json.dumps(dict(periods=payload),separators=(',',':'),allow_nan=False)+';')
    manifest=dict(built_utc=datetime.now(timezone.utc).isoformat(),frozen_strategy_sha256=hashlib.sha256((OUT/'frozen_strategy.json').read_bytes()).hexdigest(),source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src').glob('*')) if p.is_file()},input_hashes={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['config.json','data/raw/options.csv.gz','data/raw/test2026_options.csv.gz','data/raw/amzn_stock_2022_2025.csv','data/raw/test2026_stock.csv']},verification=verification['status'])
    (OUT/'run_manifest.json').write_text(json.dumps(manifest,indent=2));(OUT/'example_cycle.json').write_text(json.dumps(ex['example_facts'],indent=2))
    # Personal presentation notes are kept outside the submission repository.
    test=periods['test'];tw,tb=test['wheel'],test['buy_hold']
    notesfile=ROOT.parent/'presentation-notes.md'
    notesfile.write_text(f'''# Wheel strategy: class speaking guide

## A 90-second explanation

“My strategy follows the wheel: sell a cash-secured put, buy shares if assigned, then sell covered calls until the shares are called away. The objective is option income with controlled funding, rather than maximum exposure to a rising stock.

I used a $50,000 AMZN account. The first version kept too much cash idle. The revised version commits up to 90% of cash to put obligations, in whole contracts, and never borrows. I compared eight combinations using 2023 only. The selected rule sells {round(c['put_delta']*100)}-delta puts and {round(c['call_delta']*100)}-delta calls about {c['dte_target']} days from expiration. Calls must also have strikes at least as high as the shares’ purchase price.

Over 2023–2025, the wheel returned {pct(w['total_return'])}, compared with {pct(b['total_return'])} for fully invested AMZN. It missed part of the strong rally, but its maximum drawdown was {pct(w['max_drawdown'])} versus {pct(b['max_drawdown'])}. In the continuing account it beat the stock in 2025: {pct(w['annual_returns']['2025'])} versus {pct(b['annual_returns']['2025'])}.

I then applied the frozen rules to January–October 2026, downloaded afterward. The wheel returned {pct(tw['total_return'])}, versus {pct(tb['total_return'])} for buy-and-hold. I report both favorable and unfavorable periods. I cannot claim the study has no bias: AMZN and the earlier sample were already examined, and fills and assignment are modeled.”

## What to click during class

1. **Strategy:** explain the three cards. Put premium is compensation for accepting the obligation to buy.
2. **Results:** explain the two lines. Both accounts start at $50,000; the stock benchmark is fully invested.
3. Point to **all three calendar years**, then select **2026 YTD** to show the frozen-rule test.
4. **One cycle:** show how option premiums and stock cash flows combine. Never call premium alone profit.
5. **Portfolio:** move the date slider once. Cash plus stock less the short-option liability equals account equity.
6. Mention that the full blotter, daily ledger, all eight parameters, and source code are available. You do not need to read the audit aloud.

## A real cycle to explain

From {ex['example_facts']['start']} to {ex['example_facts']['end']}, the first completed 2026 cycle bought {ex['example_facts']['shares']} shares at {money(ex['example_facts']['put_strike'])} after put assignment and later delivered them at {money(ex['example_facts']['call_strike'])}. Across the cycle, option premiums were {money(ex['example_facts']['premium'])}, stock cash profit was {money(ex['example_facts']['stock_cashflow'])}, and commissions were {money(ex['example_facts']['fees'])}. Net profit was {money(ex['example_facts']['net_profit'])}. The website shows the major events; the blotter includes every intervening option sale and expiration.

## The numbers to remember

| Measure | Wheel | Buy-and-hold |
|---|---:|---:|
| 2023–2025 return | {pct(w['total_return'])} | {pct(b['total_return'])} |
| 2023–2025 largest decline | {pct(w['max_drawdown'])} | {pct(b['max_drawdown'])} |
| 2025 continuing-account return | {pct(w['annual_returns']['2025'])} | {pct(b['annual_returns']['2025'])} |
| 2026 Jan–Oct return | {pct(tw['total_return'])} | {pct(tb['total_return'])} |

## Likely questions

**Why 45-delta puts?** They are closer to the stock price than 30-delta puts, usually collecting more premium and increasing the chance of acquiring shares. They won the stated 2023 training comparison; they were not selected from 2026 returns.

**Why 15-delta calls?** Their strikes are farther above the stock, leaving more upside after assignment. The premium is smaller, and rallies above the strike are still capped.

**What is delta?** An option-price sensitivity to a $1 stock move. Here it is a consistent way to choose strikes. It is not an exact probability of assignment.

**Why a 90% budget?** It avoids the original one-contract account’s cash drag and retains a buffer. Whole-contract rounding can leave more than 10% unused. The number was a fixed design choice, not optimized on the test.

**Why can the wheel lose?** Assigned shares can fall by more than the premiums received. Cash security prevents an unfunded obligation; it does not prevent an investment loss.

**Does the call purchase-price floor prevent losses?** No. It avoids agreeing to sell below the gross purchase price, but the stock can remain underwater and suitable calls may not be available.

**Why didn’t it beat the whole 2023–2025 rally?** Selling puts can leave the account without shares, and selling calls gives away upside above the strike. A strong sustained rally rewards continuous ownership.

**How is look-ahead controlled?** Choose the contract from the previous session’s data, use the next session’s bid or ask, reject missing quotes without switching contracts, and select parameters on earlier data only. Engine tests also check that changing future prices cannot change earlier trades.

**Is the test bias-free?** No historical redesign can be guaranteed bias-free. The earlier AMZN results were already seen, one surviving stock was chosen, the strike grid is incomplete, and daily quotes cannot establish intraday execution. The 2026 sample was only evaluated after the rules were frozen, but it is still a historical test.

**Why no rolling?** Holding to expiration keeps the wheel’s assignments transparent and makes the rule easy to reproduce. Only the final date closes remaining positions.

**How are trades priced?** Option sales at observed bid, buybacks at ask, with $0.65 per contract per side. Stock purchases from put assignment and deliveries from call assignment occur at the strike. These are simulated fills from historical daily quotes.

**What does Sharpe mean here?** Average daily account return divided by its volatility, annualized with 252 sessions and a zero risk-free rate. It is not a Treasury-adjusted Sharpe, and a higher ratio does not imply higher total profit.

**Why is actual capital use below 90%?** The 90% figure is a ceiling on put obligations, not a constant stock weight. Option contracts require 100-share blocks, and cash also accumulates while waiting for eligible entries. The measured average capital use was {pct(w['mean_capital_usage'])} in 2023–2025 and {pct(tw['mean_capital_usage'])} in 2026.

**Why do annual and separate-year results differ?** The continuing account carries its cash and positions across December. The separate tests restart each year at $50,000, so contract rounding and starting positions differ.

## Wording to avoid

Do not say “guaranteed income,” “no risk,” “no bias,” “45% exact assignment probability,” “the best possible parameters,” or “the wheel always beats buy-and-hold.” State the measured period and result.
''')
    if (OUT/'comparison/verification.json').exists():
        from build_comparison_site import extend_site
        extend_site(ROOT)
    if (ROOT/'submission.json').exists() and json.loads((ROOT/'submission.json').read_text()).get('focus')=='PG':
        from build_pg_site import extend_site as extend_pg_site
        extend_pg_site(ROOT)
    downloads=ROOT/'docs/downloads';downloads.mkdir(exist_ok=True)
    with zipfile.ZipFile(downloads/'wheel-submission.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(ROOT.rglob('*')):
            if not p.is_file():continue
            rel=p.relative_to(ROOT)
            if any(x in rel.parts for x in ['.git','.venv','__pycache__','raw','downloads']):continue
            if p.suffix in ('.pyc','.zip'):continue
            z.write(p,Path('wheel-strategy')/rel)
    print('Simplified report, submission ZIP, and personal speaking guide built.')
if __name__=='__main__':main()
