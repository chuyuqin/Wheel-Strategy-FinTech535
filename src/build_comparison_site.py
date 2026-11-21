"""Extend the short report with all four fixed-name comparison results."""
from pathlib import Path
import json,re
import pandas as pd

def money(x):return ('−' if x<0 else '')+f'${abs(x):,.2f}'
def pct(x):return f'{x*100:.2f}%'
def pp(x):return f'{x*100:+.2f} pp'
def tr(values):return '<tr>'+''.join('<td>'+str(x)+'</td>' for x in values)+'</tr>'
def csv(p):return json.loads(pd.read_csv(p).to_json(orient='records'))
def extend_site(root):
    out=root/'docs/results/comparison';summary=json.loads((out/'summary.json').read_text());check=json.loads((out/'verification.json').read_text())
    assert check['status']=='passed'
    page=(root/'docs/index.html').read_text();old_js=(root/'docs/assets/data.js').read_text();data=json.loads(old_js[len('window.WHEEL_DATA='):-1]);stocks={}
    (root/'docs/amzn-study.html').write_text(page.replace('assets/data.js','assets/amzn-data.js').replace('assets/app.js','assets/amzn-app.js'))
    (root/'docs/assets/amzn-data.js').write_text(old_js)
    (root/'docs/assets/amzn-app.js').write_text((root/'src/amzn_app.js').read_text())
    for ticker,periods in summary.items():
        stocks[ticker]={}
        for period,r in periods.items():
            if r['status']!='ok':continue
            p=out/ticker/period;w,b=r['wheel'],r['buy_hold'];stress=r['dividend_stress']['wheel']
            finding=f"{ticker} wheel: {pct(w['total_return'])}; dividend-reinvesting buy-and-hold: {pct(b['total_return'])}; difference: {pp(r['excess_return'])}. The wheel's maximum drawdown was {pct(w['max_drawdown'])}, versus {pct(b['max_drawdown'])}. "
            finding+=f"The pre-dividend assignment scenario returned {pct(stress['total_return'])}."
            if not w['option_opens']:finding+=' No opening sale passed the stated filters; this is an inactive strategy result, not evidence that options income was earned.'
            note=r['config']['start']+' – '+r['config']['end']+'.'+' Fixed AMZN-derived rules applied to this stock; no name-specific parameter tuning. This cross-stock comparison is exploratory.'
            stocks[ticker][period]=dict(ticker=ticker,summary=r,note=note,finding=finding,daily=csv(p/'daily.csv'),events=csv(p/'blotter.csv'),benchmark=csv(p/'benchmark_daily.csv'))
    data.update(stocks=stocks,comparison=summary)
    (root/'docs/assets/data.js').write_text('window.WHEEL_DATA='+json.dumps(data,separators=(',',':'),allow_nan=False)+';')
    (root/'docs/assets/app.js').write_text((root/'src/comparison_app.js').read_text())
    page=page.replace('<title>AMZN Wheel Strategy | FINTECH 535</title>','<title>Wheel Strategy Comparison | FINTECH 535</title>')
    page=page.replace('A cash-secured AMZN wheel: simple rules, chronological parameter testing, buy-and-hold comparison and a complete trade record.','A fixed-rule wheel comparison across AMZN, KO, PG and VZ, with dividends, assignment checks and complete accounting records.')
    page=page.replace('<h1>AMZN Wheel Strategy</h1>','<h1>Does stock choice change the wheel?</h1>')
    page=page.replace('Sell puts to enter. Sell calls to exit.','AMZN · Coca-Cola · Procter &amp; Gamble · Verizon')
    page=page.replace('The goal is to earn option income while holding enough cash or shares to meet every obligation. The test asks whether that income compensates for the stock gains the wheel can miss.','The same cash-secured wheel is tested on four stocks. Each gets a $50,000 account and is compared with owning that stock, including dividends. The shortlist and rules stay fixed; every result is reported.')
    page=page.replace('AMZN continues the earlier class studies and has no cash dividends in the sample.','The shortlist consists of AMZN and three mature-business candidates named before this comparison. It is not a random sample of stocks. ')
    page=page.replace('Eight settings combine put delta','The original AMZN study compared eight settings combining put delta')
    page=page.replace('The setting with the highest net 2023 return was selected.','The setting with the highest net 2023 AMZN return was selected.')
    page=page.replace('Highlighted row: selected using 2023 only.','Highlighted row: selected using AMZN in 2023 only. That same setting is applied to KO, PG and VZ without re-optimization.')
    start=page.index('<label>View <select id="period-select">');end=page.index('</select></label>',start)+len('</select></label>')
    options=''.join(f'<option value="{t}"'+(' disabled' if len(stocks[t])<2 else '')+'>'+label+'</option>' for t,label in [('AMZN','AMZN · Amazon'),('KO','KO · Coca-Cola'),('PG','PG · Procter &amp; Gamble'),('VZ','VZ · Verizon')])
    controls='<div class="controls"><label>Stock <select id="stock-select">'+options+'</select></label><label>Period <select id="period-select"><option value="historical">Jan 2023–Sep 2024 common window</option><option value="test">2024 Jan–Sep diagnostic</option></select></label></div>'
    page=page[:start]+controls+page[end:]
    matrix='''<div class="table-wrap"><table class="comparison"><thead><tr><th>Stock</th><th>Wheel return</th><th>Buy-and-hold + DRIP</th><th>Difference</th><th>Wheel max drawdown</th><th>Wheel: dividend stress</th></tr></thead><tbody id="stock-comparison-body"></tbody></table></div><p class="fine" id="comparison-conclusion"></p><p class="fine"><a href="results/comparison/comparison.csv">Download the complete comparison CSV</a></p><p class="fine">DRIP means paid gross dividends are reinvested at the observed stock ask. A cash-dividend benchmark is retained in the downloads. The last column is a deterministic pre-dividend call-assignment scenario, not actual exercise history. This shortlist was proposed after the AMZN results were seen; it is an exploratory comparison, not a fresh stock-selection holdout. The common window ends September 30, 2024 because the daily LSEG request cap left later option coverage incomplete. The date was fixed before comparison returns were calculated. <a href="amzn-study.html">Open the original longer AMZN study</a>. Its records remain unchanged.</p>'''
    page=page.replace('<p class="period-note" id="period-note">',matrix+'<p class="period-note" id="period-note">')
    page=page.replace('Fully invested AMZN</span></div><div class="chart"','<span id="chart-stock-name">AMZN buy-and-hold (DRIP)</span></span></div><div class="chart"')
    page=page.replace('<span>Fully invested AMZN</span>','<span id="metric-bh-label">AMZN with dividends reinvested</span>',1)
    page=page.replace('Daily equity: wheel versus fully invested AMZN','Daily equity: wheel versus the selected stock with dividends reinvested')
    page=page.replace('Rank eligible monthly AMZN options','Rank eligible monthly options for the selected stock')
    page=page.replace('For the continuing 2023–2025 account','For the original AMZN continuing 2023–2025 account')
    page=page.replace('Buy-and-hold invests all of it at the first stock ask, allowing fractional shares. The wheel uses cash-secured contracts. Both liquidate at the end of the selected period. Idle cash earns 0%.','Buy-and-hold starts at the first stock ask and reinvests paid gross dividends at ask, using fractional shares. The wheel uses cash-secured contracts and receives dividends only while entitled. Both close stock and options at period end; unpaid dividends remain assets. Idle cash earns 0%.')
    page=page.replace('<div class="table-wrap annual"><table><thead><tr><th>2023–2025 continuous account</th>','<p class="fine" id="dividend-summary"></p><div class="table-wrap annual"><table><thead><tr><th id="annual-stock">AMZN · 2023–2025 continuing account</th>',1)
    marker='<th>Difference</th></tr></thead><tbody>';idx=page.index(marker,page.index('id="annual-stock"'));page=page[:idx]+page[idx:].replace(marker,'<th>Difference</th></tr></thead><tbody id="annual-body">',1)
    page=page.replace('These annual returns come from the same continuing accounts; they differ from separate one-year tests that restart with $50,000. All calendar years are shown.','Annual rows use the selected stock’s continuing common-window account. The final year is partial and labeled accordingly. The 2024 diagnostic restarts at $50,000.')
    page=page.replace('Separate account / role','Original AMZN study / role').replace('<h3>2026 execution checks</h3>','<h3>Original AMZN 2026 execution checks</h3>')
    page=page.replace('<p class="fine">Sharpe uses daily account returns','<p class="fine" id="activity-summary"></p><p class="fine">Sharpe uses daily account returns')
    example_section='<section class="section" id="example"><div class="heading"><h2 id="cycle-title">One completed wheel cycle</h2><span class="fine" id="cycle-period"></span></div><p class="intro" id="cycle-intro"></p><div class="table-wrap"><table class="left"><thead><tr><th>Date</th><th>What happened</th><th>Terms</th><th>Cash flow</th></tr></thead><tbody id="cycle-body"></tbody></table></div><p class="note" id="cycle-result"></p></section>'
    page=re.sub(r'<section class="section" id="example">.*?</section>',lambda match:example_section,page,count=1,flags=re.S)
    page=page.replace('Cash + stock − liability','Cash + stock + dividend claims − liability')
    page=page.replace('<option value="EXPIRE">Expirations</option>','<option value="EXPIRE">Expirations</option><option value="DIVIDEND_ENTITLEMENT">Dividend entitlements</option><option value="DIVIDEND_PAID">Dividend payments</option>')
    page=page.replace('<th>Collateral</th><th>Equity</th>','<th>Collateral</th><th>Dividend claim</th><th>Equity</th>')
    page=page.replace('The historical universe is the same monthly $40–$300 grid in $5 increments; missing series are not assumed listed. The study keeps AMZN rather than searching retrospectively across stocks. That preserves continuity but does not remove survivorship or stock-selection bias.','The comparison uses fixed monthly strike grids: AMZN $40–$300 by $5; KO $20–$120 by $2.50; PG $60–$250 by $5; VZ $10–$80 by $2.50. Different stock price levels need different standard strike spacing. Missing series are not assumed listed. All four selected stocks survive in this sample; survivorship and shortlist-selection bias remain.')
    extra=f'''<h3>Dividend accounting and comparison audit</h3><p>Ownership before ex-date trading earns a gross dividend receivable. Cash is credited on the payment date, or the next observed session. The benchmark reinvests paid cash at the stock ask; dividends are not counted twice or received merely because shares were purchased on the ex-date. Unpaid claims remain in final equity after the stock is sold.</p><p>The separate pre-dividend scenario assigns an in-the-money covered call at the close before ex-date if its bid-side time value is no greater than the announced dividend. The announcement must already be known. The writer then loses the upcoming dividend. This illustrates exercise sensitivity; actual holder instructions are unavailable. The scenario can improve or worsen returns because it changes the timing of share delivery and subsequent put sales; it is not a worst-case bound.</p><p>{check['unit_tests']} tests passed. Independent comparison replays reconciled {check['events_replayed']:,} events and {check['daily_portfolios_reconciled']:,} daily account values. The AMZN results match the original frozen run. The original engine and rule freeze are preserved. Its results are reproduced on the matched comparison dates; the previously published longer AMZN study is unchanged.</p><div class="downloads"><a href="results/comparison/summary.json">All comparison results</a><a href="results/comparison/verification.json">Comparison verification</a><a href="results/comparison/plan.json">Comparison plan</a><a href="results/comparison/run_manifest.json">Comparison manifest</a><a href="results/comparison/KO_data_audit.json">KO data audit</a><a href="results/comparison/PG_data_audit.json">PG data audit</a><a href="results/comparison/VZ_data_audit.json">VZ data audit</a><a id="cash-benchmark-download" href="results/comparison/AMZN/historical/benchmark_cash_daily.csv">Cash-dividend benchmark CSV</a><a id="stress-download" href="results/comparison/AMZN/historical/dividend_stress/blotter.csv">Dividend-stress blotter</a></div><pre>.venv/bin/python src/fetch_comparison.py
.venv/bin/python src/compare_stocks.py
.venv/bin/python src/verify_comparison.py
.venv/bin/python src/build_site.py</pre>'''
    page=page.replace('<h3>References</h3>',extra+'<h3>References</h3>')
    page=page.replace('<li><a href="https://developers.lseg.com/en/article-catalog/article/functions-to-find-option-rics-traded-on-different-exchanges">','<li><a href="https://developers.lseg.com/en/article-catalog/article/workspace-corporate-actions-content-set-guide">LSEG: Corporate action fields</a> — dividend announcement, ex-date, payment date and gross amount.</li><li><a href="https://developers.lseg.com/en/article-catalog/article/functions-to-find-option-rics-traded-on-different-exchanges">')
    (root/'docs/index.html').write_text(page)
    # Class guide stays separate from the submitted research source archive.
    rows=[]
    for t in ['AMZN','KO','PG','VZ']:
        h=summary[t]['historical'];q=summary[t]['test']
        if h['status']=='ok' and q['status']=='ok':rows.append(f"| {t} | {pct(h['wheel']['total_return'])} | {pct(h['buy_hold']['total_return'])} | {pct(q['wheel']['total_return'])} | {pct(q['buy_hold']['total_return'])} |")
    guide='''# Wheel comparison: class speaking guide

## A 90-second explanation

“The question is whether stock choice changes the wheel’s results. I used AMZN, Coca-Cola, Procter & Gamble and Verizon. I applied the same $50,000 account and the same rules to each stock: 45-delta puts, 15-delta covered calls, about three weeks to expiry, and cash-secured sizing within a 90% cash budget.

Those settings came from the earlier AMZN study. I did not optimize them separately for each stock. All four names and both comparison periods are shown, including unfavorable results. The shared window is January 2023 through September 2024. It ends there because the daily LSEG request limit interrupted later option downloads; I fixed the shared dates before calculating these results.

Dividend treatment matters for the three alternatives. Both accounts earn dividends only when they are entitled to them. The benchmark reinvests paid dividends. I also show a scenario in which covered calls are assigned before the ex-dividend date, taking away the writer’s dividend.

The table compares each wheel with owning its own stock. Outperformance on one stock in one period is evidence about that historical path, not a guarantee or proof that the stock is ideal for the wheel.”

## The results to use in class

| Stock | Wheel Jan 2023–Sep 2024 | Buy-and-hold + DRIP | Wheel Jan–Sep 2024 | Buy-and-hold + DRIP |
|---|---:|---:|---:|---:|
'''+ '\n'.join(rows)+'''

## Click-through order

1. Explain the three rules. Puts create an obligation to buy; calls create an obligation to sell owned shares.
2. Show the four-stock table. Compare each wheel with its own stock benchmark, not with another stock.
3. Change the stock selector to inspect the chart. Switch to the January–September 2024 diagnostic once. It is a partial year and restarts at $50,000.
4. Mention the dividend-stress column. Baseline expiration-only assignment is an assumption; pre-dividend exercise can change the result.
5. Use the selected stock’s first completed cycle as a simple example of the mechanics.
6. Move the portfolio date slider. Equity equals cash plus stock plus unpaid dividend claims minus option liabilities.
7. Point to the complete CSV records. You do not need to read the audit aloud.

## Likely questions

**Why these four stocks?** They were the named shortlist: the existing growth-stock case and three mature-business alternatives. It is an exploratory comparison, not a random sample or a claim that these are the best stocks.

**Why keep the same parameters?** This tests whether the underlying changes the outcome without choosing different rules after seeing each stock’s returns. AMZN-derived parameters may not be optimal for another stock.

**Why different strike grids?** The stock prices differ. The fixed grids include standard $2.50 spacing for KO/VZ and $5 spacing for PG/AMZN; identical nominal spacing would give the lower-priced names much coarser coverage. The full chain is still not reconstructed.

**What does delta mean?** It measures option-price sensitivity to a $1 stock move. Here it selects strikes consistently; it is not an exact assignment probability.

**Which stock worked best here?** PG was the only wheel that beat its dividend-reinvesting stock over the full common window: 22.51% versus 19.27%, with a 7.51% maximum drawdown versus 10.66%. Its first-year advantage mattered: in 2023 the wheel returned 3.64% while the stock returned −0.86%. This did not persist in every subperiod; the separate 2024 diagnostic favored buy-and-hold.

**Why does the 2024 diagnostic differ from the 2024 annual row?** The diagnostic starts January 2024 with $50,000 cash. The annual row belongs to an account that carried its cash, shares and options from 2023. Starting positions and whole-contract sizing differ.

**What is DRIP?** Reinvesting a paid dividend in additional fractional shares, priced at the observed stock ask. This keeps the benchmark invested. The cash-dividend alternative is also available.

**What is a dividend receivable?** A dividend already earned by ownership on the ex-date but not paid yet. It contributes to equity, but cannot fund new puts until it is cash.

**What is the early-assignment scenario?** Immediately before an announced ex-date, an in-the-money call with time value below the dividend is assumed assigned. The shares leave the account, so the wheel misses the dividend. Actual assignment instructions are not observed.

**Does a quiet stock automatically suit the wheel?** No. Quiet stocks can offer small premiums, wide spreads relative to premium, or insufficient eligible trades. The wheel still bears stock downside after assignment.

**Does a stock winning this table prove future outperformance?** No. The shortlist was selected after AMZN’s outcome was seen; all four are survivors; the quote and assignment models remain assumptions. No new stock or parameter winner was substituted after the comparison.

**How are fills modeled?** Previous-session contract selection, next-session bid for opening sales, ask for buybacks, and $0.65 commission per contract per side. Those are historical daily quote proxies, not actual executed orders.

**Why can cash use be below 90%?** The budget is a ceiling. Whole 100-share contracts, eligibility filters, and waiting between assignments leave additional cash unused.

**Why does the comparison end in September 2024?** The daily LSEG request allowance was exhausted before all later option chains were cached. I used the last common complete quarter with the same coverage for all four stocks, rather than mix different end dates. This scope was fixed before calculating candidate returns. The longer AMZN study is preserved separately.

**Is PG proven to be the best wheel stock?** No. It is the favorable historical case in this fixed shortlist and window. I show the other three stocks and the unfavorable 2024 diagnostic as well. This is not an independently validated stock-selection model.

**Where is the accounting?** The website has exact daily holdings, every event, complete ledgers, benchmark trades and dividend-stress records for each stock and period.
'''
    (root.parent/'presentation-notes.md').write_text(guide)
    readme=root/'README.md';text=readme.read_text();marker='\n## Four-stock comparison extension\n';text=text.split(marker)[0]
    text+=marker+'\nThe fixed AMZN rule is also applied to KO, PG and VZ over the common January 3, 2023–September 30, 2024 window and a separate January–September 2024 diagnostic. The shorter scope was explicitly selected by the user after the daily API request cap was exhausted, before comparison returns were calculated. Original longer requested periods remain documented and are not reported as completed cross-stock tests. Primary buy-and-hold reinvests paid gross dividends at ask. The originally specified cash-dividend benchmark remains a reported sensitivity. The accounting refinement was recorded before candidate returns were calculated. Baseline and announced-dividend assignment stresses have full blotters and daily ledgers. See `docs/results/comparison/plan.json`, `summary.json`, `verification.json` and per-ticker folders. No original AMZN rule or result was replaced.\n\nWith the existing private cache, run `src/normalize_comparison_cache.py`, `src/compare_stocks.py`, `src/verify_comparison.py`, then `src/build_site.py`. The matched-window analysis needs no further downloads. For a new entitled LSEG retrieval, `src/fetch_comparison.py` checks the remaining daily allowance, preserves completed responses and can be resumed after the provider resets the allowance. A full fresh universe may need more than one daily allowance. The original AMZN reproduction workflow above remains valid.\n'
    text=text.replace('# AMZN Wheel Strategy','# Wheel Strategy Comparison',1)
    introduction='The main website compares AMZN, KO, PG and VZ over January 2023–September 2024, with a separate January–September 2024 diagnostic. The shorter common scope was selected after the LSEG daily download cap. [Original longer AMZN report](docs/amzn-study.html).\n\n'
    if introduction not in text:text=text.replace('## Selected rules',introduction+'## Original AMZN selected rules',1)
    readme.write_text(text)
