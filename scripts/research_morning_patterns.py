"""Offline next-session comparison; outputs stay off the live dashboard."""
import json
from pathlib import Path
from collections import Counter
import pandas as pd
from engine.daily_context import daily_context


def main():
    cache=sorted(Path('data').glob('market-context-daily-*.json'))[-1]
    histories={k:pd.DataFrame(v).assign(timestamp=lambda x:pd.to_datetime(x.timestamp)) for k,v in json.loads(cache.read_text()).items()}
    days=sorted({ts.date() for frame in histories.values() for ts in frame.timestamp})[-20:]
    totals=Counter()
    for day in days:
        observations=[]
        for key,frame in histories.items():
            prior=frame[frame.timestamp.dt.date < day]
            current=frame[frame.timestamp.dt.date == day]
            if len(prior)<22 or current.empty: continue
            context=daily_context(prior,day.isoformat())
            if context.get('status')!='READY': continue
            change=(current.iloc[-1].close/prior.iloc[-1].close-1)*100
            observations.append((change,context))
        observations.sort(key=lambda x:x[0],reverse=True)
        for index,(change,context) in enumerate(observations):
            group='compression' if context['compression'] else 'other'
            totals[group+'_observations']+=1
            totals[group+'_top10']+=index<10
            totals[group+'_bottom10']+=index>=len(observations)-10
            totals[group+'_abs3pct']+=abs(change)>=3
    result={'sessions':len(days),'universe':'Current F&O members only; survivorship bias', 'counts':{k:int(v) for k,v in totals.items()},
            'limitations':'Daily OHLC comparison only. No historical timestamped OI/news archive. Not an opening-signal backtest or calibrated top-gainer probability.'}
    Path('data/morning-pattern-research.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
if __name__=='__main__': main()
