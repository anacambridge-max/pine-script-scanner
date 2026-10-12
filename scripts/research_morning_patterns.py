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
    cohorts={}
    for day_index,day in enumerate(days):
        observations=[]
        for key,frame in histories.items():
            prior=frame[frame.timestamp.dt.date < day]
            current=frame[frame.timestamp.dt.date == day]
            if len(prior)<22 or current.empty: continue
            context=daily_context(prior,day.isoformat())
            if context.get('status')!='READY': continue
            change=(current.iloc[-1].close/prior.iloc[-1].close-1)*100
            prior_volume=float(prior.volume.iloc[:-1].tail(20).mean())
            context['volume_multiple']=float(prior.volume.iloc[-1])/prior_volume if prior_volume>0 else 0
            prior_row=prior.iloc[-1]
            context['bull_day']=prior_row.close>prior_row.open
            observations.append((change,context))
        observations.sort(key=lambda x:x[0],reverse=True)
        for index,(change,context) in enumerate(observations):
            split='holdout' if day_index>=15 else 'discovery'
            groups={
                'baseline': True,
                'compression_inside': context['compression'] and context['inside_day'],
                'compression_downtrend_near_low': context['compression'] and context['trend']=='DOWNTREND' and 'NEAR 20-SESSION LOW' in context['labels'],
                'compression_uptrend': context['compression'] and context['trend']=='UPTREND',
                'strong_bull_high_volume': context['bull_day'] and context['body_ratio']>=.65 and context['close_location']>=.8 and context['volume_multiple']>=1.5,
                'strong_bear_high_volume': not context['bull_day'] and context['body_ratio']>=.65 and context['close_location']<=.2 and context['volume_multiple']>=1.5,
            }
            for name,matched in groups.items():
                if matched:
                    cohort=cohorts.setdefault(name,{}).setdefault(split,Counter())
                    cohort['observations']+=1
                    cohort['top10']+=index<10
                    cohort['bottom10']+=index>=len(observations)-10
                    cohort['gain3pct']+=change>=3
                    cohort['loss3pct']+=change<=-3
            group='compression' if context['compression'] else 'other'
            totals[group+'_observations']+=1
            totals[group+'_top10']+=index<10
            totals[group+'_bottom10']+=index>=len(observations)-10
            totals[group+'_abs3pct']+=abs(change)>=3
    result={'sessions':len(days),'universe':'Current F&O members only; survivorship bias', 'counts':{k:int(v) for k,v in totals.items()},
            'combined_patterns':{name:{split:{k:int(v) for k,v in count.items()} for split,count in splits.items()} for name,splits in cohorts.items()},
            'limitations':'Daily OHLC comparison only. No historical timestamped OI/news archive. Not an opening-signal backtest or calibrated top-gainer probability.'}
    Path('data/morning-pattern-research.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
if __name__=='__main__': main()
