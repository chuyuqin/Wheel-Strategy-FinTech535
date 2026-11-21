"""Reproduce the historical study with the original cache and original freeze.
Unlike `research.py select`, this does not create or overwrite a rule freeze.
"""
from dataclasses import replace
from research import *
def main():
    freeze=json.loads((OUT/'frozen_strategy.json').read_text());plan=json.loads((OUT/'research_plan.json').read_text())
    assert digest(ROOT/'src/backtest.py')==freeze['engine_sha256']
    assert digest(ROOT/'src/research.py')==freeze['research_script_sha256']
    assert digest(ROOT/'data/raw/options.csv.gz')==freeze['training_input_sha256'],'Original normalized cache required'
    m=Market.load();rows=[]
    for name,c in grid():
        row=dict(id=name,config=asdict(c))
        for label,key in [('training','training'),('validation','validation'),('diagnostic','previously_seen_diagnostic')]:
            row[label]=run(m,replace(c,start=plan[key][0],end=plan[key][1]),OUT/'study'/label/name)
        rows.append(row)
    rows.sort(key=lambda x:(-x['training']['wheel']['total_return'],-x['training']['wheel']['max_drawdown'],x['id']))
    assert rows[0]['id']==freeze['selected_id']
    dump(OUT/'parameter_study.json',rows);periods=json.loads((OUT/'periods.json').read_text());c=Config(**freeze['config'])
    for key in ['historical','training','validation','diagnostic']:
        old=periods[key];periods[key]=dict(label=old['label'],**run(m,replace(c,start=old['config']['start'],end=old['config']['end']),OUT/'selected'/key))
    dump(OUT/'periods.json',periods);print('Historical results replayed; original freeze preserved.')
if __name__=='__main__':main()
