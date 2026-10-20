from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
root=Path(r'C:\Users\jerem\Downloads\the_antidote\2026_WM_Hackathon\Data_Science\artifacts\march_2024')
out=Path(r'C:\Users\jerem\Documents\Codex\2026-10-19\c-users-jerem-downloads-aisvesseltracks2013-zip\outputs')
frames=[]; rows=[]; approaches=[]
labels=['0-15','15-30','30-60','60-120','120+']
for model in ['quadratic','xgboost']:
 f=pd.read_csv(root/model/'test_predictions.csv',dtype={'mmsi':str});f['actual_remaining']=(pd.to_datetime(f.arrival_time)-pd.to_datetime(f.decision_time)).dt.total_seconds()/60
 f['abs_error']=f.error_minutes.abs();f['horizon']=pd.cut(f.actual_remaining,[0,15,30,60,120,np.inf],labels=labels,include_lowest=True);frames.append(f)
 for horizon,g in f.groupby('horizon',observed=True):
  a=g.groupby('approach_id').agg(mae=('abs_error','mean'),bias=('error_minutes','mean'),within5=('abs_error',lambda v:(v<=5).mean()))
  rows.append(dict(model=model,horizon_minutes=str(horizon),snapshots=len(g),approaches=g.approach_id.nunique(),approach_weighted_mae_minutes=a.mae.mean(),snapshot_median_error_minutes=g.abs_error.median(),snapshot_p90_error_minutes=g.abs_error.quantile(.9),approach_weighted_bias_minutes=a.bias.mean(),within5_percent=100*a.within5.mean()))
 a=f.groupby(['approach_id','mmsi']).agg(snapshots=('abs_error','size'),mae_minutes=('abs_error','mean'),maximum_error_minutes=('abs_error','max'),bias_minutes=('error_minutes','mean'),arrival_time=('arrival_time','first')).reset_index();a['model']=model;approaches.append(a)
 print('OVERALL',model,'median',f.abs_error.median(),'p90',f.abs_error.quantile(.9),'max',f.abs_error.max(),'approach_p90',a.mae_minutes.quantile(.9),'expired',int((f.predicted_remaining_minutes<0).sum()),'max_horizon',f.actual_remaining.max(),'median_horizon',f.actual_remaining.median())
pd.testing.assert_frame_equal(frames[0][['approach_id','decision_time']],frames[1][['approach_id','decision_time']])
b=pd.DataFrame(rows);b.to_csv(out/'eta_test_horizon_breakdown.csv',index=False);print('HORIZONS\n'+b.round(2).to_string(index=False))
a=pd.concat(approaches);a.sort_values(['model','mae_minutes'],ascending=[True,False]).to_csv(out/'eta_test_approach_errors.csv',index=False);print('WORST\n'+a.sort_values('mae_minutes',ascending=False).groupby('model',sort=False).head(3).round(2).to_string(index=False))
p=a.pivot(index='approach_id',columns='model',values='mae_minutes');print('XGB WINS',int((p.xgboost<p.quadratic).sum()),'of',len(p))
fig,ax=plt.subplots(figsize=(9,4.5));x=np.arange(5);width=.36
for offset,model in [(-width/2,'quadratic'),(width/2,'xgboost')]:
 v=b[b.model==model].set_index('horizon_minutes').reindex(labels);ax.bar(x+offset,v.approach_weighted_mae_minutes,width,label=model)
ax.set_xticks(x,labels);ax.set_xlabel('Actual minutes remaining until reference crossing');ax.set_ylabel('Approach-weighted MAE (minutes)');ax.set_title('Nominal test data: ETA error by prediction horizon');ax.legend();fig.tight_layout();fig.savefig(out/'eta_horizon_errors.png',dpi=160)
