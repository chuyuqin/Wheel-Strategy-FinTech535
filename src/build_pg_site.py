"""Build the PG submission page without changing any research results."""
from pathlib import Path
import json,re
import pandas as pd

def money(x):return ('−' if x<0 else '')+f'${abs(x):,.2f}'
def pct(x):return f'{100*x:.2f}%'
def pp(x):return f'{100*x:+.2f} pp'
def row(values):return '<tr>'+''.join('<td>'+str(x)+'</td>' for x in values)+'</tr>'
def extend_site(root):
    out=root/'docs/results/comparison';summary=json.loads((out/'summary.json').read_text());check=json.loads((out/'verification.json').read_text());assert check['status']=='passed'
    historical=summary['PG']['historical'];diag=summary['PG']['test'];w=historical['wheel'];b=historical['buy_hold']
    # Preserve the complete comparison as a separate research record.
    page=(root/'docs/index.html').read_text();data_js=(root/'docs/assets/data.js').read_text()
    (root/'docs/comparison.html').write_text(page.replace('assets/data.js','assets/comparison-data.js').replace('assets/app.js','assets/comparison-app.js'))
    (root/'docs/assets/comparison-data.js').write_text(data_js);(root/'docs/assets/comparison-app.js').write_text((root/'src/comparison_app.js').read_text())
    data=json.loads(data_js[len('window.WHEEL_DATA='):-1]);pg=data['stocks']['PG']
    for key,r in pg.items():
        r['note']=r['summary']['config']['start']+' – '+r['summary']['config']['end']+' · PG historical observations with simulated execution.'
    (root/'docs/assets/data.js').write_text('window.WHEEL_DATA='+json.dumps(dict(stocks=dict(PG=pg)),separators=(',',':'),allow_nan=False)+';')
    (root/'docs/assets/app.js').write_text((root/'src/pg-app.js').read_text())
    events=pd.read_csv(out/'PG/historical/blotter.csv');opens=events.loc[events.action.eq('SELL_TO_OPEN')];spread=opens.ask-opens.bid;mid_cost=float((-opens.quantity*spread*50).sum())
    metrics=''.join(row([name,money(s['ending_equity']),pct(s['cagr']),pct(s['annualized_volatility']),f"{s['sharpe_zero_rf']:.2f}",pct(s['max_drawdown'])]) for name,s in [('PG wheel',w),('PG buy-and-hold + DRIP',b)])
    pnl=''.join(row([name,money(value)]) for name,value in [('Option premiums received',w['premium_received']),('Option buybacks',-w['buyback_cost']),('Net stock cash flows',w['stock_cashflow']),('Dividends earned',w['dividends_earned']),('Option commissions',-w['fees']),('Net account profit',w['net_profit'])])
    annual=''.join(row([year+(' through Sep 30' if year=='2024' else ''),pct(w['annual_returns'][year]),pct(b['annual_returns'][year]),pp(w['annual_returns'][year]-b['annual_returns'][year])]) for year in w['annual_returns'])
    selection=''.join(row([t,pct(summary[t]['historical']['wheel']['total_return']),pct(summary[t]['historical']['buy_hold']['total_return']),pp(summary[t]['historical']['excess_return'])]) for t in ['AMZN','KO','PG','VZ'])
    pg_audit=json.loads((out/'PG_data_audit.json').read_text())
    method=f'''<details><summary>Execution rules, data and verification</summary><ol class="rules"><li><strong>Contract selection.</strong> Use the prior session’s stock close, delta and activity. Monthly PG contracts must have 14–28 calendar days to expiry and absolute delta within 0.10 of the target. Rank by delta distance, maturity distance, strike and RIC. Puts are below the stock price; calls are above it and at least the shares’ gross purchase price. The fixed strike grid is $60–$250 in $5 increments, not the full historical chain.</li><li><strong>Liquidity and fills.</strong> Require prior-session volume ≥ 100, open interest ≥ 500, positive two-sided quotes, and a spread no greater than $1 and 25% of midpoint. Execute the selected contract at the next session’s bid only if that session’s quote passes the same price filters. Otherwise skip without substituting a different contract. Buybacks use observed ask. Stock sales use bid. No midpoint fills are assumed.</li><li><strong>Funding and costs.</strong> Put lots = floor(90% × available cash ÷ (100 × strike)), before receiving premium. Calls cover the owned shares, with one short option series at a time. Each option costs $0.65 per contract per side. Stock and assignment fees are $0; idle cash earns 0%; taxes and regulatory fees are omitted.</li><li><strong>Expiration and exit.</strong> Hold to expiry without discretionary rolls. An option at least $0.01 in the money at the stock close is assumed physically assigned; otherwise it expires. Record 100 shares per contract at the strike, with all lots in a batch using the same convention. Remaining stock and options close at observed sides on the final date.</li><li><strong>Dividends and benchmark.</strong> Ownership before ex-date trading earns a gross dividend receivable. It contributes to equity immediately and becomes spendable cash on the pay date or the next observed session. The benchmark invests $50,000 at the initial stock ask, permits fractional shares, and reinvests paid dividends at ask. The cash-dividend alternative is also retained. Legal settlement balances are not reconstructed.</li><li><strong>Valuation and early exercise.</strong> Mark stock at bid and short options at ask. Missing asks can be carried for at most two sessions for valuation, never fills; longer gaps and missing terminal prices fail the run. A separate scenario assigns an ITM covered call just before an announced ex-date when bid-side time value is below the dividend. It returned {pct(historical['dividend_stress']['wheel']['total_return'])} for PG with {historical['dividend_stress']['wheel']['pre_dividend_assignments']} triggered pre-dividend assignments. This does not establish that actual early assignment was impossible.</li></ol><h3>Evidence for the fill assumptions</h3><p>Across {w['option_opens']} opening sales and {w['contracts_sold']} contracts, the median observed bid–ask width was {money(float(spread.median()))} per share; the 90th percentile was {money(float(spread.quantile(.9)))}. Selling at bid rather than midpoint reduced receipts by {money(mid_cost)} before commissions. These spreads support an observable execution-cost assumption. Daily quotes do not establish simultaneous NBBOs, depth, or guaranteed fills.</p><h3>Audit trail</h3><p>The PG run contains {historical['sessions']} daily portfolios and {w['events']} events: opening sales, closing purchases, expirations, assignments, stock transfers and dividends. It used {w['carried_mark_days']} carried option marks. Independent accounting replays passed, and {check['unit_tests']} synthetic-fixture tests passed. Test fixtures do not supply performance. Raw LSEG responses stay local; their request parameters, retrieval dates and hashes are summarized in the data audit.</p><div class="downloads"><a href="results/comparison/PG_data_audit.json">PG data audit</a><a href="results/comparison/verification.json">Verification</a><a href="results/comparison/run_manifest.json">Run manifest</a><a href="results/comparison/PG/historical/summary.json">PG metrics</a><a id="skips-download" href="results/comparison/PG/historical/skips.csv">Skipped decisions</a><a id="cash-benchmark-download" href="results/comparison/PG/historical/benchmark_cash_daily.csv">Cash-dividend benchmark</a><a id="stress-download" href="results/comparison/PG/historical/dividend_stress/blotter.csv">Assignment scenario blotter</a></div><h3>Reproduce from the original local cache</h3><pre>python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python src/normalize_comparison_cache.py
.venv/bin/python src/compare_stocks.py
.venv/bin/python src/verify_comparison.py
.venv/bin/python src/build_site.py</pre><p class="fine">The source ZIP includes the engine, rules, tests, site generator and derived results. Downloading raw history requires an entitled LSEG Workspace session. Fresh retrievals may reflect vendor revisions and require more than one daily allowance. The original AMZN freeze is preserved; no PG-specific parameter search was added.</p></details><details id="selection"><summary>Research selection and limitations</summary><p>PG was selected after comparing AMZN, KO, PG and VZ using the same wheel rules. The common study window was fixed before those comparison returns were calculated. It ends September 30, 2024 because LSEG’s daily request cap left later option coverage incomplete; the last common complete quarter supported identical dates for every stock. The four-stock record and earlier AMZN research remain available.</p><div class="table-wrap"><table><thead><tr><th>Jan 2023–Sep 2024</th><th>Wheel</th><th>Buy-and-hold + DRIP</th><th>Difference</th></tr></thead><tbody>{selection}</tbody></table></div><p>Focusing on the favorable PG result introduces selection bias. The sample is not an untouched validation set, and all four companies are surviving stocks. The separate 2024 restart returned {pct(diag['wheel']['total_return'])} for the wheel versus {pct(diag['buy_hold']['total_return'])} for buy-and-hold. It provides a less favorable diagnostic, not independent validation. These results do not establish future profitability or identify the best wheel stock.</p><p><a href="comparison.html">Full four-stock comparison</a> · <a href="results/comparison/plan.json">Recorded comparison plan</a> · <a href="amzn-study.html">Original AMZN study</a></p></details><details><summary>References</summary><ul class="source-list"><li><a href="https://www.schwab.com/learn/story/three-things-to-know-about-wheel-strategy">Charles Schwab — Three Things to Know About the Wheel Strategy</a>. Prof. Vestal’s reference for puts, assignment, covered calls and the strategy’s tradeoffs.</li><li><a href="https://www.optionseducation.org/referencelibrary/faq/options-assignment">OIC — Options Assignment</a> · <a href="https://www.theocc.com/clearance-and-settlement/clearing/equity-options-product-specifications">OCC — Equity Options</a>. American-style exercise and standard physical delivery.</li><li><a href="https://developers.lseg.com/en/article-catalog/article/workspace-corporate-actions-content-set-guide">LSEG — Corporate Actions Content</a>. Dividend announcement, ex-date, payment date and gross-amount fields.</li><li>LSEG Workspace historical daily PG stock, option and dividend observations. Exact requests and response hashes are retained in the local cache and summarized in the audit.</li></ul></details>'''
    finding=f"The PG wheel returned {pct(w['total_return'])}, compared with {pct(b['total_return'])} for dividend-reinvesting buy-and-hold: {pp(historical['excess_return'])}. The wheel earned {money(w['net_profit'])} after modeled costs, with a maximum drawdown of {pct(w['max_drawdown'])} versus {pct(b['max_drawdown'])}."
    values=dict(ending_equity=money(w['ending_equity']),bh_equity=money(b['ending_equity']),wheel_return=pct(w['total_return']),bh_return=pct(b['total_return']),excess_return=pp(historical['excess_return']),max_drawdown=pct(w['max_drawdown']),bh_drawdown=pct(b['max_drawdown']),comparison_rows=metrics,pnl_rows=pnl,annual_rows=annual,finding=finding,dividend_summary=f"Gross dividends earned: wheel {money(w['dividends_earned'])}; buy-and-hold {money(b['dividends_earned'])}. Paid benchmark dividends are reinvested at the stock ask.",diagnostic_return=pct(diag['wheel']['total_return']),diagnostic_bh_return=pct(diag['buy_hold']['total_return']),method_section=method)
    page=(root/'src/pg-page.html').read_text().replace('<h1>The wheel on PG.</h1>','<h1>PG Wheel Strategy</h1>')
    for k,v in values.items():page=page.replace('{{'+k+'}}',str(v))
    assert not re.search(r'\{\{\w+\}\}',page)
    (root/'docs/index.html').write_text(page)
    (root/'README.md').write_text(f'''# PG Wheel Strategy

FINTECH 535 · Chuyu Qin · November 1, 2026

The submission website is `docs/index.html`. The full PG study covers January 3, 2023–September 30, 2024. Starting capital is $50,000 per account. The wheel returned {pct(w['total_return'])} versus {pct(b['total_return'])} for PG buy-and-hold with dividend reinvestment. Maximum drawdowns were {pct(w['max_drawdown'])} and {pct(b['max_drawdown'])}.

The website includes the thesis, three trading rules, one completed cycle, exact daily holdings, searchable blotter, ledger, dividend accounting, execution evidence and research-selection disclosures. PG was selected after a four-stock comparison; the result is exploratory. The January–September 2024 restart favors buy-and-hold. The common window was limited by cached option coverage after the daily LSEG download cap; no longer cross-stock result is claimed.

## View and publish

Open `docs/index.html` directly, or run `python3 -m http.server 8000 --directory docs`. Publish the `main` branch, `/docs` directory with GitHub Pages. All charts and data are bundled; viewing requires no LSEG access. Publication is left to the repository owner.

## Reproduce from the original private cache

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python src/normalize_comparison_cache.py
.venv/bin/python src/compare_stocks.py
.venv/bin/python src/verify_comparison.py
.venv/bin/python src/build_site.py
```

Raw responses in `data/raw/` are ignored by Git and excluded from the ZIP. Fetching history requires an entitled LSEG Workspace session. `src/fetch_comparison.py` checks the remaining allowance and can resume completed caches after the provider resets its quota. Fresh historical observations may differ after vendor revisions.

## Records

`docs/results/comparison/PG/historical/` contains the main daily ledger, blotter, benchmark records, metrics, skipped decisions and dividend-assignment scenario. `PG/test/` contains the separate January–September 2024 restart diagnostic; the internal folder name is not a claim of an unseen holdout. The original frozen AMZN settings were transferred to PG without name-specific retuning.

`comparison.html` preserves all four comparison stocks. `amzn-study.html` preserves the longer original AMZN report. The comparison plan versions, input audits, source manifest and verification results are under `docs/results/`. The main accounting identities, fill proxies and remaining biases are explained in the website. Synthetic fixtures test accounting only and never enter performance.
''')
    notes=f'''# PG wheel: class speaking guide

## A 90-second explanation

“I tested a wheel strategy on Procter & Gamble. I first sell cash-secured puts. If a put is assigned, I buy 100 shares per contract at the strike, then sell covered calls against those shares. When the calls are assigned, I deliver the shares and return to puts.

The account starts with $50,000. Puts target 45 delta and calls 15 delta, about 21 days from expiration. Put obligations stay within 90% of available cash, and calls must have strikes at least as high as the shares’ purchase price. The account never borrows.

From January 2023 through September 2024, the wheel returned {pct(w['total_return'])}, versus {pct(b['total_return'])} for owning PG with dividends reinvested. Its largest drawdown was {pct(w['max_drawdown'])}, versus {pct(b['max_drawdown'])}.

I selected PG after comparing four stocks, so this is an exploratory case study. The separate January–September 2024 restart favored buy-and-hold: {pct(diag['wheel']['total_return'])} versus {pct(diag['buy_hold']['total_return'])}. I show that limitation rather than claiming consistent outperformance.”

## Remember these numbers

- Full-study wheel return: **{pct(w['total_return'])}**.
- Buy-and-hold with reinvested dividends: **{pct(b['total_return'])}**.
- Difference: **{pp(historical['excess_return'])}**.
- Wheel ending equity: **{money(w['ending_equity'])}**; net profit **{money(w['net_profit'])}**.
- Maximum drawdown: **{pct(w['max_drawdown'])}** versus **{pct(b['max_drawdown'])}**.

## What created the profit?

| Component | Amount |
|---|---:|
| Premiums received | {money(w['premium_received'])} |
| Option buybacks | {money(-w['buyback_cost'])} |
| Net stock cash flows | {money(w['stock_cashflow'])} |
| Dividends earned | {money(w['dividends_earned'])} |
| Option commissions | {money(-w['fees'])} |
| Net account profit | {money(w['net_profit'])} |

Do not describe premiums alone as profit. The account also owes an option liability while a short contract is open.

## Click-through order

1. Explain the three rule cards.
2. Show the two return lines and the maximum drawdown figures.
3. Point to the visible selection-context note. PG was selected after comparison.
4. Show the first completed PG cycle. It is chosen chronologically, not as the best trade.
5. Move the portfolio date to **2023-04-20**: the account has a dividend receivable. It has been earned but is not cash yet.
6. Mention that every trade and daily balance is available in CSV form. You do not need to read the audit aloud.

## Likely questions

**Why 45-delta puts?** They are nearer the stock price than 30-delta puts, generally collecting more premium and increasing assignment exposure. The setting came from the earlier AMZN parameter study; PG was not separately optimized.

**Why 15-delta calls?** They allow more room for stock appreciation than nearer-money calls, in exchange for less premium.

**What is delta?** Sensitivity of an option’s price to a $1 stock move. Here it helps select strikes. It is not an exact assignment probability.

**Why PG?** It was the favorable case among AMZN, KO, PG and VZ in the common window. In 2023, the PG wheel returned {pct(w['annual_returns']['2023'])}, while PG buy-and-hold returned {pct(b['annual_returns']['2023'])}. This is a historical explanation, not a guarantee or unbiased stock-selection model.

**Why did the diagnostic lose to buy-and-hold?** Income strategies can miss stock gains while waiting for put assignment or after shares are called away. Results depend on the price path and starting holdings.

**Why do the 2024 annual row and restart diagnostic differ?** The continuing account carries shares, options and cash from 2023. The restart begins January 2024 entirely in $50,000 cash. Whole-contract sizing and positions differ.

**Does the call strike floor prevent losses?** No. The stock can fall below its purchase price while the account waits for an eligible call.

**What does cash-secured mean?** Cash is reserved for 100 × strike × put contracts. Assignment can be funded without borrowing. It does not remove stock downside.

**How are dividends handled?** Entitlement becomes an asset on ex-date for existing owners. Spendable cash arrives on payment date. The benchmark reinvests paid cash; the wheel can use paid cash in later trades. The same dividend is not counted twice.

**What about early assignment?** A separate announced-dividend call-assignment scenario is reported. It triggered {historical['dividend_stress']['wheel']['pre_dividend_assignments']} pre-dividend assignments for PG in the full study. That does not prove early exercise cannot occur.

**Why this date window?** A daily LSEG cap interrupted later option downloads. The matched common window was fixed before candidate returns were calculated. September 2024 is explicitly a partial year.

**How is look-ahead controlled?** Prior-session contract selection and next-session observed bid/ask fills; no switching contracts using execution-day information. Engine tests check causality. Selecting PG after seeing the comparison still creates selection bias, which is disclosed.

**What is Sharpe here?** An annualized ratio of mean daily account return to volatility using a zero risk-free rate. It is not adjusted for Treasury yields. Different capital deployment also affects comparisons.

**What can still go wrong?** Stock losses can exceed premiums, upside is capped by calls, and actual fills, exercise decisions, settlement and taxes may differ from the model.
'''
    (root.parent/'presentation-notes.md').write_text(notes)
