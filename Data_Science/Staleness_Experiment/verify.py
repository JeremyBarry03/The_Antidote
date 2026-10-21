"""Independent reconciliation and natural-gap recovery descriptions."""
from pathlib import Path
import json
import sys
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay
from eta_baselines.features import FeatureBuilder


def main():
    out=HERE/'results'
    p=pd.read_csv(out/'evaluation_predictions.csv',parse_dates=['decision_time','arrival_time','prediction'])
    assert len(p)==2402*5*3
    assert not p.duplicated(['decision_id','withheld_minutes','system']).any()
    assert p.groupby(['withheld_minutes','system']).size().eq(2402).all()
    assert ((p.prediction-p.arrival_time).dt.total_seconds()/60-p.error_minutes).dropna().abs().max()<1e-6
    for _,g in p.groupby(['withheld_minutes','system']):
        assert g.approach_id.nunique()==112
    config=OptimizedConfig.load(HERE.parent/'Optimized_Model/config.json')
    summary=pd.read_csv(out/'condition_summary.csv')
    existing=pd.read_csv(config.output_directory/'results/evaluation_primary/condition_summary.csv')
    for delay,scenario in [(0,'nominal'),(15,'stale_15')]:
        new=summary.loc[summary.system.eq('B') & summary.withheld_minutes.eq(delay)].iloc[0]
        old=existing.loc[existing.system.eq('B') & existing.scenario.eq(scenario)].iloc[0]
        assert abs(new.approach_mae-old.approach_weighted_mae_minutes)<1e-6
        assert abs(new.coverage-old.output_coverage)<1e-12
    dataset=load_replay(config)
    builder=FeatureBuilder(config.baseline.gate,config.baseline.features)
    # Future-data invariance tested against actual supplied history at a middle decision.
    d=dataset.partition('evaluation').iloc[100]
    h=dataset.histories[d.approach_id]
    original=builder.snapshot(h,d.decision_time)
    past=builder.snapshot(h.loc[h.time<=d.decision_time],d.decision_time)
    pd.testing.assert_frame_equal(original,past)
    b=p.loc[p.system.eq('B') & p.withheld_minutes.eq(0)]
    gaps=pd.read_csv(out/'natural_gaps.csv',parse_dates=['gap_start','gap_end'])
    pairs=[]
    for gap in gaps.loc[gaps.split.eq('evaluation')].itertuples():
        g=b.loc[b.approach_id.eq(gap.approach_id)].sort_values('decision_time')
        during=g.loc[g.decision_time.gt(gap.gap_start)&g.decision_time.lt(gap.gap_end)]
        after=g.loc[g.decision_time.ge(gap.gap_end)&g.decision_time.le(gap.gap_end+pd.Timedelta(minutes=5))]
        if during.empty or after.empty:
            continue
        a,c=during.iloc[-1],after.iloc[0]
        pairs.append(dict(approach_id=gap.approach_id,mmsi=gap.mmsi,gap_start=gap.gap_start,gap_end=gap.gap_end,
            gap_minutes=gap.gap_minutes,during_decision=a.decision_time,after_decision=c.decision_time,
            during_age=a.age_minutes,after_age=c.age_minutes,during_error=a.error_minutes,after_error=c.error_minutes,
            absolute_error_change=abs(c.error_minutes)-abs(a.error_minutes)))
    pd.DataFrame(pairs).to_csv(out/'natural_gap_resumption_pairs.csv',index=False)
    note=dict(prediction_rows=len(p),distinct_decisions=p.decision_id.nunique(),approaches=p.approach_id.nunique(),
        future_data_invariance_passed=True,timestamp_error_reconciliation_passed=True,
        evaluation_natural_gaps=int(gaps.split.eq('evaluation').sum()),
        evaluation_gaps_with_decisions=int((gaps.split.eq('evaluation') & gaps.decisions_inside.gt(0)).sum()),
        natural_resumption_pairs=len(pairs),
        natural_gap_caveat='Before/after gap resumption changes decision time and vessel state; observational, not causal.')
    (out/'independent_checks.json').write_text(json.dumps(note,indent=2))
    # Regenerate illustrative extremes from saved results, using the active trigger condition.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    a=pd.read_csv(out/'per_approach.csv')
    wide=a.loc[a.withheld_minutes.eq(15)].pivot(index='approach_id',columns='system',values='mae')
    delta=(wide.motion-wide.B).sort_values()
    examples={'largest_motion_recovery':delta.index[0],'largest_motion_failure':delta.index[-1]}
    natural=p.loc[p.withheld_minutes.eq(0) & p.natural_gap_active,'approach_id'].drop_duplicates()
    if len(natural): examples['natural_gap']=natural.iloc[0]
    for label,identity in examples.items():
        delay=0 if label=='natural_gap' else 15
        g=p.loc[p.approach_id.eq(identity)&p.withheld_minutes.eq(delay)]
        fig,(ax,age)=plt.subplots(2,1,figsize=(11,7),sharex=True)
        for system,sg in g.groupby('system'):
            ax.plot(sg.decision_time,sg.error_minutes,label=system)
        ax.axhline(0,color='black',linewidth=.8)
        ax.set(ylabel='Signed ETA error (minutes)',title=f'{label}: {identity}; {delay} min withheld')
        ax.legend()
        b=g.loc[g.system.eq('B')]; age.plot(b.decision_time,b.age_minutes,color='purple')
        age.set(ylabel='Latest report age (minutes)',xlabel='Decision time (UTC)')
        fig.autofmt_xdate(); fig.tight_layout(); fig.savefig(out/f'{label}.png',dpi=160); plt.close(fig)
    validation=json.loads((out/'validation.json').read_text()); validation['examples']=examples
    validation['example_withholding_minutes']=15
    validation['original_and_15min_baseline_reproduced']=True
    (out/'validation.json').write_text(json.dumps(validation,indent=2))
    report=(out/'REPORT.md').read_text(encoding='utf-8').replace('at ten-minute withholding','at fifteen-minute withholding')
    (out/'REPORT.md').write_text(report,encoding='utf-8')
    print(json.dumps(note,indent=2))
    if pairs:
        frame=pd.DataFrame(pairs)
        print('Natural resumption mean absolute-error change:',frame.absolute_error_change.mean())


if __name__=='__main__':
    main()
