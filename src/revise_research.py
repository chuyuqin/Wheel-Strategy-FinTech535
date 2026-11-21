"""Rerun the fixed four-stock comparison with lagged Treasury cash interest.

Writes a separate correction; never overwrites the archived, zero-rate study.
Run: python src/revise_research.py
"""
from dataclasses import replace,asdict
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,html
import numpy as np
import pandas as pd
from backtest import Config
from compare_stocks import market
from rates_revision import TreasuryRates,RateAwareWheel,rate_aware_benchmark

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/results/revision'
RATE_FILE=OUT/'treasury_dgs3mo.csv'

def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')

def audit(d,e,c,rates,kind,haircut):
    """Replay cash, equity, interest eligibility and excess returns independently."""
    balance=c.initial_cash
    for event in e.itertuples():
        balance+=event.cashflow
        assert np.isclose(balance,event.cash_after,atol=1e-6),('event cash',event.event_id)
    totals=e.groupby('date').cashflow.sum()
    reconstructed=c.initial_cash+d.date.map(totals).fillna(0).cumsum()
    assert np.allclose(reconstructed,d.cash,atol=1e-6)
    liability=d.short_liability if 'short_liability' in d else 0
    assert np.allclose(d.equity,d.cash+d.stock_value+d.dividend_receivable-liability,atol=1e-6)
    for event in e.loc[e.action.eq('INTEREST')].itertuples():
        before=d.loc[d.date.eq(event.accrual_start)].iloc[0]
        reserved=before.reserved_cash if kind=='wheel' else 0
        expected_principal=max(0,before.cash-reserved)
        assert np.isclose(event.interest_principal,expected_principal,atol=1e-6)
        factor=1.
        for day in pd.date_range(pd.Timestamp(event.accrual_start)+pd.Timedelta(days=1),event.accrual_end):
            eligible=rates.rates.loc[rates.rates.index<day]
            assert not eligible.empty
            factor*=1+max(0,float(eligible.iloc[-1])-haircut)/365
        assert np.isclose(event.cashflow,expected_principal*(factor-1),atol=1e-8)
    for i in range(1,len(d)):
        assert np.isclose(d.risk_free_return.iloc[i],rates.factor(d.date.iloc[i-1],d.date.iloc[i]))
    assert np.allclose(d.excess_return,d.daily_return-d.risk_free_return)

def run_case(m,divs,c,symbol,rates,folder,haircut=0):
    folder.mkdir(parents=True,exist_ok=True)
    wheel=RateAwareWheel(m,c,symbol,divs,rates=rates,haircut=haircut)
    d,e,s=wheel.run()
    bd,be,bs=rate_aware_benchmark(m,c,symbol,divs,rates,True,haircut)
    cd,ce,cs=rate_aware_benchmark(m,c,symbol,divs,rates,False,haircut)
    for kind,dd,ee in [('wheel',d,e),('buy_hold',bd,be),('buy_hold_cash',cd,ce)]:
        audit(dd,ee,c,rates,'wheel' if kind=='wheel' else 'benchmark',haircut)
        dd.to_csv(folder/(kind+'_daily.csv'),index=False)
        ee.to_csv(folder/(kind+'_blotter.csv'),index=False)
    # Exact cash-flow contribution identities, not a causal attribution model.
    contribution=dict(option_premiums=s['premium_received'],option_buybacks=-s['buyback_cost'],
        net_stock_cashflows=s['stock_cashflow'],dividends=s['dividends_earned'],
        commissions=-s['fees'],cash_interest=s['interest_earned'])
    assert np.isclose(sum(contribution.values()),s['net_profit'],atol=1e-6)
    s['contributions_dollars']=contribution
    s['mean_cash_fraction']=float((d.cash/d.equity).mean())
    s['mean_free_cash_fraction']=float((d.free_cash/d.equity).mean())
    s['mean_stock_equity_fraction']=float((d.stock_value/d.equity).mean())
    result=dict(config=asdict(c),cash_rate_haircut=haircut,wheel=s,buy_hold=bs,buy_hold_cash=cs,
        excess_return=s['total_return']-bs['total_return'],sessions=len(d),audit='passed')
    dump(folder/'summary.json',result)
    return result

def pct(x):return f'{x*100:.2f}%'
def cash(x):return f'${x:,.2f}'
def fnum(x):return f'{x:.2f}'

def page(summary,verification):
    rows=[];detail=[];attrib=[];sensitivity=[]
    for ticker in ['AMZN','KO','PG','VZ']:
        r=summary[ticker]['historical'];w,b=r['wheel'],r['buy_hold']
        rows.append([ticker,pct(w['total_return']),pct(b['total_return']),f"{100*r['excess_return']:+.2f} pp",fnum(w['sharpe_excess_treasury']),fnum(b['sharpe_excess_treasury']),cash(w['interest_earned']),pct(w['max_drawdown']),pct(b['max_drawdown'])])
        detail.append([ticker,pct(w['stock_exposure_fraction']),pct(w['mean_stock_equity_fraction']),pct(w['mean_free_cash_fraction']),w['put_assignments'],w['call_assignments'],w['skip_reasons'].get('no_eligible_C',0),cash(w['premium_received']-w['buyback_cost'])])
        z=w['contributions_dollars'];attrib.append([ticker]+[cash(z[k]) for k in ['option_premiums','option_buybacks','net_stock_cashflows','dividends','commissions','cash_interest']]+[cash(w['net_profit'])])
        diag=summary[ticker]['test'];hair=summary[ticker]['haircut_100bp'];floor=summary[ticker]['without_cost_floor']
        sensitivity.append([ticker,pct(diag['wheel']['total_return']),pct(diag['buy_hold']['total_return']),pct(hair['wheel']['total_return']),pct(floor['wheel']['total_return'])])
    def table(headers,rows):
        return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+html.escape(str(x))+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'
    pg=summary['PG']['historical'];amzn=summary['AMZN']['historical'];vz=summary['VZ']['historical'];ko=summary['KO']['historical']
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Wheel research revision | FINTECH 535</title><style>
    :root{color-scheme:light;--ink:#142738;--muted:#506172;--line:#d7e1e5;--teal:#007d75}*{box-sizing:border-box}body{margin:0;background:#f6f8f7;color:var(--ink);font:16px/1.65 system-ui,sans-serif}a{color:var(--teal)}header,main,footer{max-width:1180px;margin:auto;padding:24px}nav{display:flex;flex-wrap:wrap;gap:24px;font-size:14px}h1{font-size:clamp(32px,5vw,58px);line-height:1.12;max-width:980px;letter-spacing:-.04em}h2{font-size:26px;line-height:1.3}h3{margin-top:28px}p{max-width:960px}.eyebrow{text-transform:uppercase;letter-spacing:.14em;color:var(--teal);font-size:12px;font-weight:700}.lead{font-size:21px;max-width:900px}.note{padding:18px;border-left:4px solid var(--teal);background:#eaf3ef}.section{border-top:1px solid var(--line);padding:26px 0}.scroll{overflow:auto;margin:20px 0}table{width:100%;border-collapse:collapse;font-size:14px;background:white}th,td{padding:12px 14px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}th:first-child,td:first-child{text-align:left}th{background:#e9f0f1;color:#314d5c}code{font-size:.9em;background:#e8eeee;padding:2px 5px}li{margin-bottom:8px}footer{border-top:1px solid var(--line);font-size:13px;color:var(--muted)}@media(max-width:600px){header,main,footer{padding:20px}h1{margin-top:24px}th,td{padding:10px}}
    </style></head><body><header><nav><a href="final-cycle.html">Final Cycle assignment</a><a href="index.html">Original PG study</a><a href="#results">Corrected comparison</a><a href="#method">Rate methodology</a><a href="results/revision/summary.json">Download results</a></nav><p class="eyebrow">FINTECH 535 · Chuyu Qin · Research correction · November 16, 2026</p><h1>Test the wheel’s mechanism.<br>Show every stock.</h1><p class="lead">A four-stock correction with historical Treasury opportunity costs, interest on unencumbered cash, and a measurable prediction for future evaluation.</p><p class="note">The original PG result was selected after observing all four outcomes. This revision leads with the complete comparison. It does not turn the existing data into an unseen test, extend the historical window, or claim that PG was selected in advance.</p></header><main>
    <section class="section"><h2>A testable thesis and its mechanism</h2><p><strong>Prediction:</strong> for the fixed AMZN, KO, PG and VZ universe, annual wheel-minus-buy-and-hold total returns will be negatively rank-correlated with the stocks’ annual dividend-reinvested buy-and-hold returns. The lower two stocks by buy-and-hold return will have a higher median wheel excess return than the upper two. Evaluate both inequalities on the full 2027 calendar year with the present rules, all four names and identical dates; do not replace a loser or tune parameters from those outcomes.</p><p><strong>Mechanism:</strong> puts can leave the account in cash during a rally; covered calls sell upside beyond their strikes. Premiums and cash interest can offset these opportunity costs when gains are modest, but do not eliminate losses after assignment. The prediction concerns relative performance across stock paths, not a promise that the wheel earns a positive absolute return or beats cash.</p><p>This prediction is formulated on November 16, 2026, after seeing the old sample. It is a proposed forward evaluation protocol, not evidence that the old study was preregistered. The current historical comparison is descriptive support and can falsify a simplistic “wheel always wins” claim; it cannot validate the new hypothesis out of sample.</p></section>
    <section class="section" id="results"><h2>Corrected matched-window results</h2><p>January 3, 2023–September 30, 2024 · $50,000 initial capital for every account · identical fixed wheel rules and quotes · interest credited before each session’s trades. Sharpe uses Treasury-excess daily returns.</p>'''+table(['Stock','Wheel','Buy & hold + DRIP','Wheel − B&H','Wheel Sharpe','B&H Sharpe','Wheel cash interest','Wheel max DD','B&H max DD'],rows)+'''
    <p>The primary comparison uses the rate-aware rerun. Original zero-rate outputs remain in <a href="comparison.html">the archived four-stock study</a>; their older numbers should not be mixed with this table. Rate-aware results and independent audit records are <a href="results/revision/summary.json">downloadable</a>.</p></section>
    <section class="section"><h2>Why PG looked better—and why the others did not</h2><p>These are measured differences consistent with the proposed mechanism, not a causal experiment isolating each feature.</p>'''+table(['Stock','Sessions owning shares','Mean stock value / equity','Mean free cash / equity','Put assignments','Call assignments','No eligible call days','Premium less buybacks'],detail)+f'''
    <p><strong>AMZN:</strong> buy-and-hold gained {pct(amzn['buy_hold']['total_return'])}, versus {pct(amzn['wheel']['total_return'])} for the wheel. The wheel owned shares on only {pct(amzn['wheel']['stock_exposure_fraction'])} of sessions and had average stock value equal to {pct(amzn['wheel']['mean_stock_equity_fraction'])} of equity. Its very large underlying rally makes this limited participation and called-away upside costly. Premium receipts alone are not a fair comparison with the uncapped underlying gain.</p><p><strong>PG:</strong> buy-and-hold gained {pct(pg['buy_hold']['total_return'])}, versus {pct(pg['wheel']['total_return'])} for the wheel. A more modest total gain makes the premium cushion more competitive with foregone upside. But modest gains alone cannot explain PG’s win, because KO and VZ also had modest total gains. The distinguishing observed wheel path had {pg['wheel']['put_assignments']} put assignments and {pg['wheel']['call_assignments']} call assignments, producing {cash(pg['wheel']['stock_cashflow'])} of net stock cash-flow gains plus {cash(pg['wheel']['premium_received']-pg['wheel']['buyback_cost'])} in premiums net of buybacks. KO and VZ each had only one put assignment and one call assignment, with zero net stock cash-flow gain over the complete liquidated sample. PG’s outcome therefore combined recurring option income with favorable assignment-to-delivery stock gains, rather than premium collection alone.</p><p><strong>KO and VZ:</strong> buy-and-hold gained {pct(ko['buy_hold']['total_return'])} and {pct(vz['buy_hold']['total_return'])}, respectively. Their wheel results were {pct(ko['wheel']['total_return'])} and {pct(vz['wheel']['total_return'])}. Dividend timing also matters: KO’s wheel earned {cash(ko['wheel']['dividends_earned'])} of dividends versus {cash(ko['buy_hold']['dividends_earned'])} in buy-and-hold; VZ’s earned {cash(vz['wheel']['dividends_earned'])} versus {cash(vz['buy_hold']['dividends_earned'])}. The wheel earns dividends only when it owns shares before ex-date. A high dividend yield alone therefore does not imply a wheel advantage.</p><p><strong>Cost-basis floor:</strong> requiring a call strike at least equal to the shares’ gross purchase price can leave the account long shares without an eligible call after a decline. This retains downside while sometimes preventing premium collection. It avoids committing to sell below gross purchase price; it does not prevent an economic loss. “No eligible call” counts also include delta, maturity and liquidity filters, so the count is not attributed entirely to the floor. The matched no-floor diagnostic below improves KO and PG but reduces VZ’s return; removing the floor is not a universal repair.</p><h3>Where each dollar of wheel profit came from</h3><p>The contribution rows sum exactly to net profit. Stock cash flows include assignment purchases and delivery/liquidation sales; this cash-flow identity does not separately estimate delta, gamma or volatility risk premia.</p>'''+table(['Stock','Premiums','Buybacks','Net stock cash flows','Dividends earned','Commissions','Cash interest','Net profit'],attrib)+'''
    </section><section class="section"><h2>Sensitivity instead of another winner search</h2><p>The 2024 restart reuses dates already in the main study and is not an independent holdout. The cash-credit sensitivity earns one percentage point less than the Treasury yield, floored at zero. The final column removes only the cost-basis floor; it is a diagnostic comparison, not a newly selected optimal policy.</p>'''+table(['Stock','2024 restart wheel','2024 restart B&H','Full window: cash yield −1pp','Full window: no cost floor'],sensitivity)+'''
    </section><section class="section" id="method"><h2>Historical rates, cash yield and Sharpe</h2><ul><li><strong>Source:</strong> <a href="https://fred.stlouisfed.org/series/DGS3MO">Federal Reserve H.15 three-month constant-maturity Treasury yield via FRED (DGS3MO)</a>. The <a href="results/revision/treasury_dgs3mo.csv">downloaded daily observations</a>, source URL, retrieval time and SHA-256 are retained. This is an investment-yield series, not a Treasury total-return index.</li><li><strong>No same-day rate lookahead:</strong> accrue each calendar day using only the latest nonmissing observation strictly earlier than that day. Weekends and market holidays earn calendar-day interest. Missing observations are carried forward only from the past, with a ten-day staleness limit. Historical observations were downloaded now and can reflect revisions; this is not an ALFRED vintage reconstruction.</li><li><strong>Eligible cash:</strong> previous-close positive cash minus the full short-put strike obligation; a dividend receivable is excluded until payment. Reserved put collateral earns no interest in this conservative main convention. Multiply eligible cash by the calendar-day compounded ACT/365 factor. The same residual-cash convention applies to both buy-and-hold benchmarks. This cash yield is a modeled opportunity-cost proxy, not a claim that a broker pays the full Treasury rate.</li><li><strong>Economic rerun:</strong> interest is posted to spendable cash before new trades. Position sizes are recomputed from the changed cash balance; this is not an ex-post return boost added to the old equity curve. The option-selection parameters, fee assumptions, stock list and historical dates are held fixed.</li><li><strong>Risk-free excess Sharpe:</strong> for each observed session interval, account return minus the Treasury cash-accrual return for that same interval. Sharpe = mean(excess) / sample standard deviation(excess) × √252. The first observation includes execution friction with a zero risk-free interval because inception is the first session close. Volatility and drawdown continue to use total account returns. Annualizing daily Sharpe assumes conventional trading-day scaling and does not adjust for serial correlation.</li><li><strong>Costs and comparison:</strong> $0.65 option fee per contract per side, bid-side short sales and ask-side buybacks, dividends and assignment follow the archived study. All-stock price histories and option coverage still end at the same pre-existing common date. No raw licensed LSEG data are published here.</li></ul><h3>What remains unresolved</h3><p>The historical window ends in September 2024 because that was the last common complete cached quarter after the data-download quota constrained the previous project. This remains a limitation rather than an economic justification for the period. Newer complete stock, option and dividend data are needed to evaluate a genuinely later period. Daily quote proxies do not establish actual fills, queue priority, intraday NBBO or real early exercise. Survivorship, the small selected universe, prior parameter selection and this retrospective explanation remain limitations.</p><h3>Verification and reproducibility</h3><p>All revised wheel and benchmark runs passed independent event-to-cash replay, equity identities, interest-principal eligibility, calendar-day accrual and excess-return checks. Unit tests cover rate lagging, weekend accrual, staleness and unavailable history. See <a href="results/revision/verification.json">verification</a> and <a href="results/revision/manifest.json">source manifest</a>. Run <code>python src/revise_research.py</code> with the original ignored private cache available and the bundled public Treasury CSV; the archived zero-rate report is not overwritten.</p></section></main><footer>FINTECH 535 · Chuyu Qin · Research revision, November 16, 2026. Historical observations; simulated execution and interest. <a href="final-cycle.html">Return to the nightly assignment</a>.</footer></body></html>'''

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    rates=TreasuryRates.load(RATE_FILE)
    cfg=Config(**json.loads((ROOT/'docs/results/frozen_strategy.json').read_text())['config'])
    plan=json.loads((ROOT/'docs/results/comparison/plan.json').read_text())
    summary={};runs=0
    for ticker in ['AMZN','KO','PG','VZ']:
        summary[ticker]={}
        for period,(start,end) in plan['periods'].items():
            m,divs=market(ticker,period);c=replace(cfg,start=start,end=end,cash_rate=0)
            r=run_case(m,divs,c,plan['universe'][ticker]['ric'],rates,OUT/ticker/period)
            summary[ticker][period]=r;runs+=1
            print(ticker,period,pct(r['wheel']['total_return']),pct(r['buy_hold']['total_return']),flush=True)
            if period=='historical':
                for label,cc,haircut in [('haircut_100bp',c,.01),('without_cost_floor',replace(c,call_cost_floor=False),0)]:
                    summary[ticker][label]=run_case(m,divs,cc,plan['universe'][ticker]['ric'],rates,OUT/ticker/label,haircut);runs+=1
    verification=dict(status='passed',economic_cases=runs,account_paths=runs*3,unit_tests=10,
        checks=['cash event replay','daily cash reconstruction','equity identity','previous-close free-cash interest principal','lagged calendar-day accrual including weekends','Treasury-excess returns','PnL contribution identity'])
    dump(OUT/'summary.json',summary);dump(OUT/'verification.json',verification)
    manifest=dict(retrieved_at=datetime.now(timezone.utc).isoformat(),
        source='https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS3MO&cosd=2022-12-01&coed=2024-10-01',
        series='DGS3MO',units='percent per annum, investment basis',
        rates_sha256=hashlib.sha256(RATE_FILE.read_bytes()).hexdigest(),
        source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'src/rates_revision.py',ROOT/'src/revise_research.py',ROOT/'src/comparison_engine.py',ROOT/'src/backtest.py']},
        conventions='Lagged daily yield; ACT/365; free cash excludes put collateral; no interest on dividend receivables; no ALFRED vintage reconstruction',
        old_sample='2023-01-03 through 2024-09-30; 2024 restart overlaps main sample',
        performance_claim='Descriptive corrected rerun, not new out-of-sample evidence')
    dump(OUT/'manifest.json',manifest)
    (ROOT/'docs/research-revision.html').write_text(page(summary,verification))
    print('Research correction complete:',runs,'economic cases',runs*3,'audited account paths',flush=True)

if __name__=='__main__':main()
