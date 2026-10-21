"""Follow-up staleness experiment; existing source data and models are read-only."""
from pathlib import Path
import hashlib
import json
import sys

import joblib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay
from eta_baselines.features import FeatureBuilder
from eta_baselines.motion import history_velocity, local_positions

DELAYS = (0, 2, 5, 10, 15)
THRESHOLDS = (2, 5, 10, 15)
SEED = 20261020


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def features(builder, reports, decision):
    row = builder.snapshot(reports, decision.decision_time).iloc[0].to_dict()
    row.update(decision.to_dict())
    return row


def motion_estimate(reports, time, config):
    """Constant eastward progress toward gate; unsupported motion falls back to B."""
    last = reports.iloc[-1]
    recent = reports.loc[reports.time >= last.time - pd.Timedelta(minutes=10)]
    if len(recent) < 3 or (recent.time.iloc[-1] - recent.time.iloc[0]).total_seconds() < 60:
        return np.nan
    if recent.time.diff().dt.total_seconds().max() > 300:
        return np.nan
    vx, vy, residual = history_velocity(recent, config.baseline.gate)
    x, y = local_positions(recent.tail(1), config.baseline.gate)[0]
    if not np.isfinite(vx + vy + residual) or vx >= -.25 or residual > 500 or x <= 0:
        return np.nan
    seconds = -x / vx
    gate = config.baseline.gate
    predicted_lat = (gate.south_latitude + gate.north_latitude) / 2 + (y + vy * seconds) / 111195
    if not gate.south_latitude <= predicted_lat <= gate.north_latitude or seconds > 6 * 3600:
        return np.nan
    arrival = last.time + pd.Timedelta(seconds=seconds)
    if arrival < time:
        return np.nan
    return arrival


def aggregate(frame, keys):
    rows = []
    for labels, g in frame.groupby(keys, observed=True):
        if not isinstance(labels, tuple):
            labels = (labels,)
        out = dict(zip(keys, labels))
        valid = g.loc[g.available & g.error_minutes.notna()].copy()
        valid['ae'] = valid.error_minutes.abs()
        per = valid.groupby('approach_id').ae.mean()
        out.update(scheduled=len(g), available=len(valid), approaches=g.approach_id.nunique(),
                   coverage=len(valid)/len(g), approach_mae=per.mean(),
                   decision_median_error=valid.ae.median(), decision_p95_error=valid.ae.quantile(.95),
                   over_15_minutes_rate=valid.ae.gt(15).mean(),
                   intervention_rate=g.intervened.mean(), verification_request_rate=g.requested.mean())
        rows.append(out)
    return pd.DataFrame(rows)


def paired(frame, left, right, label):
    """Vessel-cluster bootstrap of approach-weighted, matched absolute-error changes."""
    p = frame.pivot(index=['mmsi', 'approach_id', 'decision_id'], columns='system', values='error_minutes')
    if left not in p or right not in p:
        return None
    p = p[[left, right]].dropna()
    d = (p[right].abs() - p[left].abs()).rename('difference').reset_index()
    per = d.groupby(['mmsi', 'approach_id']).difference.mean().reset_index()
    if per.empty:
        return None
    groups = [g.difference.to_numpy() for _, g in per.groupby('mmsi')]
    rng = np.random.default_rng(SEED)
    samples = [np.concatenate([groups[i] for i in rng.integers(len(groups), size=len(groups))]).mean()
               for _ in range(1000)]
    return dict(comparison=label, left=left, right=right, matched_decisions=len(d),
                approaches=len(per), vessels=len(groups), mean_change=per.difference.mean(),
                ci_low=np.quantile(samples, .025), ci_high=np.quantile(samples, .975),
                decision_improved_share=d.difference.lt(0).mean(),
                decision_worsened_share=d.difference.gt(0).mean())


def main():
    out = HERE / 'results'
    out.mkdir(exist_ok=True)
    config = OptimizedConfig.load(HERE.parent / 'Optimized_Model/config.json')
    model_path = config.frozen_baseline_model('xgboost')
    before = digest(model_path)
    dataset = load_replay(config)
    model = joblib.load(model_path)
    builder = FeatureBuilder(config.baseline.gate, config.baseline.features)
    protocol = dict(delays_minutes=DELAYS, threshold_candidates_minutes=THRESHOLDS,
        motion_support='>=3 points, >=60 seconds history, <=300 second gaps, westward vx<-0.25 m/s, residual<=500m, crossing inside gate, <=6h extrapolation, future crossing',
        tuning='March validation only; minimize equal-condition/equal-approach MAE; ties prefer fewer interventions',
        evaluation='April 8-21 follow-up; previously inspected, not pristine holdout',
        verification='At most one latest original report at or before decision time; only if newer than cutoff. Historical oracle assumes external verification access.',
        natural_gap='Consecutive within-approach observations >2 minutes apart; no invented observations',
        large_error_minutes=15, bootstrap_seed=SEED, model_sha256=before)
    (out/'protocol.json').write_text(json.dumps(protocol, indent=2))
    gaps, base_rows, verified_rows, metadata = [], [], [], []
    decisions = dataset.decisions.loc[dataset.decisions.split.isin(['validation', 'evaluation'])]
    for ai, (identity, group) in enumerate(decisions.groupby('approach_id')):
        history = dataset.histories[identity].sort_values('time')
        for j in range(1, len(history)):
            a, b = history.iloc[j-1], history.iloc[j]
            minutes = (b.time-a.time).total_seconds()/60
            if minutes > 2:
                gaps.append(dict(approach_id=identity, mmsi=group.mmsi.iloc[0], split=group.split.iloc[0],
                    gap_start=a.time, gap_end=b.time, gap_minutes=minutes,
                    before_speed_knots=a.sog, moving_before=bool(a.sog > .5),
                    decisions_inside=int(((group.decision_time > a.time) & (group.decision_time < b.time)).sum())))
        times = history.time.to_numpy()
        for _, decision in group.iterrows():
            time = decision.decision_time
            original = history.loc[history.time <= time]
            latest = original.tail(1)
            for delay in DELAYS:
                cutoff = time-pd.Timedelta(minutes=delay)
                supplied = original.loc[original.time <= cutoff]
                idx = len(metadata)
                meta = decision.to_dict()
                meta.update(row_id=idx, withheld_minutes=delay, available=not supplied.empty,
                            actual_remaining_minutes=(decision.arrival_time-time).total_seconds()/60,
                            natural_gap_active=any(g['approach_id']==identity and g['gap_start'] < time < g['gap_end'] for g in gaps))
                if supplied.empty:
                    meta.update(age_minutes=np.nan, motion_arrival=pd.NaT, update_available=False)
                else:
                    meta['age_minutes']=(time-supplied.time.iloc[-1]).total_seconds()/60
                    meta['motion_arrival']=motion_estimate(supplied,time,config)
                    meta['update_available']=bool(latest.time.iloc[0] > supplied.time.iloc[-1])
                    row=features(builder,supplied,decision); row['row_id']=idx; base_rows.append(row)
                    restored=pd.concat([supplied,latest]).drop_duplicates().sort_values('time')
                    row=features(builder,restored,decision); row['row_id']=idx; verified_rows.append(row)
                metadata.append(meta)
        if ai % 15 == 0:
            print('Built',ai+1,'approaches',flush=True)
    meta=pd.DataFrame(metadata).set_index('row_id')
    for rows,column in [(base_rows,'b_arrival'),(verified_rows,'verified_arrival')]:
        predictions=model.predict(pd.DataFrame(rows))
        meta[column]=pd.Series(predictions.predicted_arrival_time.to_numpy(),index=predictions.row_id)
    pd.DataFrame(gaps).to_csv(out/'natural_gaps.csv',index=False)
    meta.reset_index().to_csv(out/'replay_inputs.csv',index=False)

    def materialize(threshold, selected=None):
        frame=meta if selected is None else meta.loc[selected]
        outputs=[]
        for system in ['B','motion','verified_update']:
            f=frame.copy(); f['system']=system
            trigger=f.available & f.age_minutes.ge(threshold)
            f['requested']=trigger if system=='verified_update' else False
            possible=f.motion_arrival.notna() if system=='motion' else f.update_available
            f['intervened']=trigger & possible if system!='B' else False
            f['prediction']=f.b_arrival
            if system!='B':
                f.loc[f.intervened,'prediction']=f.loc[f.intervened,'motion_arrival' if system=='motion' else 'verified_arrival']
            f['error_minutes']=(pd.to_datetime(f.prediction)-f.arrival_time).dt.total_seconds()/60
            outputs.append(f)
        return pd.concat(outputs).reset_index()

    tuning=[]
    for threshold in THRESHOLDS:
        p=materialize(threshold, meta.split.eq('validation'))
        s=aggregate(p,['withheld_minutes','system'])
        for system in ['motion','verified_update']:
            g=s.loc[s.system.eq(system)]
            tuning.append(dict(system=system,threshold=threshold,objective=g.approach_mae.mean(),intervention_rate=g.intervention_rate.mean()))
    tune=pd.DataFrame(tuning); tune.to_csv(out/'march_threshold_selection.csv',index=False)
    chosen={system:float(g.sort_values(['objective','intervention_rate','threshold'],ascending=[True,True,False]).iloc[0].threshold)
            for system,g in tune.groupby('system')}
    (out/'locked_thresholds.json').write_text(json.dumps(chosen,indent=2))
    frames=[]
    for system in ['B','motion','verified_update']:
        f=materialize(chosen.get(system,2),meta.split.eq('evaluation'))
        frames.append(f.loc[f.system.eq(system)])
    p=pd.concat(frames,ignore_index=True)
    p['age_band']=pd.cut(p.age_minutes,[-np.inf,2,5,10,15,np.inf],right=False,labels=['<2','2-5','5-10','10-15','15+'])
    p['horizon_band']=pd.cut(p.actual_remaining_minutes,[-np.inf,15,30,60,np.inf],labels=['<=15','15-30','30-60','>60'])
    p.to_csv(out/'evaluation_predictions.csv',index=False)
    summary=aggregate(p,['withheld_minutes','system']); summary.to_csv(out/'condition_summary.csv',index=False)
    aggregate(p,['withheld_minutes','age_band','system']).to_csv(out/'by_age.csv',index=False)
    aggregate(p,['withheld_minutes','horizon_band','system']).to_csv(out/'by_horizon.csv',index=False)
    aggregate(p.loc[p.withheld_minutes.eq(0)],['natural_gap_active','system']).to_csv(out/'natural_gap_summary.csv',index=False)
    approach=p.assign(ae=p.error_minutes.abs()).groupby(['approach_id','mmsi','withheld_minutes','system']).agg(mae=('ae','mean'),scheduled=('available','size'),available=('available','sum'),requests=('requested','sum'),interventions=('intervened','sum')).reset_index()
    approach.to_csv(out/'per_approach.csv',index=False)
    comparisons=[]
    for delay,g in p.groupby('withheld_minutes'):
        for system in ['motion','verified_update']:
            row=paired(g,'B',system,f'{delay} min withheld: correction minus B')
            if row: row['withheld_minutes']=delay; comparisons.append(row)
        b=g.loc[g.system.eq('B')].copy()
        original=p.loc[p.system.eq('B') & p.withheld_minutes.eq(0)].copy()
        original['system']='original_B'; b['system']='withheld_B'
        row=paired(pd.concat([original,b]),'original_B','withheld_B',f'{delay} min withheld B minus original B')
        if row: row['withheld_minutes']=delay; comparisons.append(row)
    pd.DataFrame(comparisons).to_csv(out/'paired_uncertainty.csv',index=False)
    # Verification work is reported separately; no invented human duration.
    request=p.loc[p.system.eq('verified_update')].groupby('withheld_minutes').agg(requests=('requested','sum'),restored_updates=('intervened','sum'),decisions=('decision_id','size'),approaches=('approach_id','nunique'))
    request['requests_per_approach']=request.requests/request.approaches
    request['requests_without_eligible_update']=request.requests-request.restored_updates
    request.to_csv(out/'verification_workload.csv')
    fig,ax=plt.subplots(figsize=(9,5))
    for system,g in summary.groupby('system'):
        ax.plot(g.withheld_minutes,g.approach_mae,'o-',label=system)
    ax.set(xlabel='Minutes of recent reports deliberately withheld',ylabel='Approach-weighted MAE (minutes)',title='April follow-up: matched staleness experiment')
    ax.legend(); fig.tight_layout(); fig.savefig(out/'comparison.png',dpi=160); plt.close(fig)
    # Select examples reproducibly by approach-level motion gain, not by arbitrary hand picking.
    wide=approach.loc[approach.withheld_minutes.eq(15)].pivot(index='approach_id',columns='system',values='mae')
    difference=(wide.motion-wide.B).sort_values()
    selected={'largest_motion_recovery':difference.index[0],'largest_motion_failure':difference.index[-1]}
    natural=p.loc[p.withheld_minutes.eq(0) & p.natural_gap_active,'approach_id'].drop_duplicates()
    if len(natural): selected['natural_gap']=natural.iloc[0]
    for label,identity in selected.items():
        delay=0 if label=='natural_gap' else 15
        g=p.loc[p.approach_id.eq(identity) & p.withheld_minutes.eq(delay)]
        fig,(ax,age)=plt.subplots(2,1,figsize=(11,7),sharex=True)
        for system,sg in g.groupby('system'):
            ax.plot(sg.decision_time,sg.error_minutes,label=system)
        ax.axhline(0,color='black',linewidth=.8); ax.set(ylabel='Signed ETA error (minutes)',title=f'{label}: {identity}; {delay} min withheld'); ax.legend()
        b=g.loc[g.system.eq('B')]; age.plot(b.decision_time,b.age_minutes,color='purple')
        age.set(ylabel='Latest report age (minutes)',xlabel='Decision time (UTC)')
        fig.autofmt_xdate(); fig.tight_layout(); fig.savefig(out/f'{label}.png',dpi=160); plt.close(fig)
    assert digest(model_path)==before
    assert (pd.to_datetime(meta.loc[meta.available,'verified_arrival']).notna()).all()
    assert not p.loc[p.withheld_minutes.eq(0) & p.system.eq('verified_update'),'intervened'].any()
    assert not p.loc[~p.available,'prediction'].notna().any()
    assert (p.loc[p.available,'age_minutes'] >= p.loc[p.available,'withheld_minutes']-1e-9).all()
    checks=dict(model_unchanged=True,no_forecast_without_history=True,no_verification_intervention_on_original_feed=True,
        cutoff_age_invariant=True,scheduled_evaluation_decisions=int(decisions.split.eq('evaluation').sum()),
        evaluation_prediction_rows=len(p),examples=selected)
    (out/'validation.json').write_text(json.dumps(checks,indent=2))
    text=['# Staleness experiment results','',
        'Existing frozen B; original source files untouched. April results are follow-up analyses, not a new pristine holdout. No models were retrained.',
        '',f'March-selected thresholds (minutes): {chosen}.',
        '', '## April condition results', '', summary.round(4).to_csv(index=False),
        '', '## Paired changes and vessel-cluster bootstrap intervals', '',pd.DataFrame(comparisons).round(4).to_csv(index=False),
        '', '## Interpretation limits','',
        'Natural gaps are observed within cached qualifying approach histories. They do not establish receiver latency, corruption, or causation. Gaps with no scheduled decision are counted separately. Unresolved/nonarrival episodes are excluded by the existing cohort.',
        'Matched withholding isolates missing recent information on the original-report reference; it is simulated, not naturally observed latency. The reference itself is not perfect ground truth.',
        'Motion is a constant-velocity gate-crossing alternative with conservative support rules; otherwise it retains B. It can fail under stops and turns. Thresholds use March development, but other April findings had been inspected before this experiment.',
        'Verified update restores at most one historical report measured by the decision time. This is conditional on a successful external verification; it is not an autonomous repair. Natural gaps have no invented update. Requests are counted, but no human effort duration or trust study has been measured.',
        'Error is relative to analytical gate crossing, not verified docking. Report coverage and failure tails alongside averages. A 15-minute large-error threshold is descriptive, not a validated operational tolerance.',
        'Examples are explicitly selected largest motion recovery/loss at fifteen-minute withholding, where the locked motion trigger activates; the natural-gap plot is the first qualifying evaluation approach by ID. These are illustrations, not representative performance estimates.',
        '', 'Run: `python Staleness_Experiment/run.py` from Data_Science. See protocol.json, locked_thresholds.json, and validation.json for settings and checks.']
    (out/'REPORT.md').write_text('\n'.join(text),encoding='utf-8')
    print(summary.to_string(index=False),flush=True)
    print('Thresholds:',chosen,'Checks:',checks,flush=True)


if __name__=='__main__':
    main()
