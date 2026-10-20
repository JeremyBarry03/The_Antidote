"""Run isolated source-level checks; never load downloaded joblib artifacts."""
import ast,json,pathlib,contextlib,io
import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder
root=pathlib.Path(r'C:\Users\jerem\Downloads\the_antidote\2026_WM_Hackathon\work\repo_review')
repo=root/'Maritime_eta_prediction'
notebook=json.loads((repo/'AIS analysis.ipynb').read_text(encoding='utf8'))
checks={}
def isolated_function(source,name,namespace):
 tree=ast.parse(source);node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
 exec(compile(ast.Module(body=[node],type_ignores=[]),'<reviewed isolated function>','exec'),namespace)
 return namespace[name]
prepare=isolated_function(''.join(notebook['cells'][10]['source']),'prepare_data_for_eta',{'pd':pd,'np':np,'LabelEncoder':LabelEncoder})
track=pd.DataFrame({'MMSI':[1,1,1],'BaseDateTime':pd.date_range('2024-03-01',periods=3,freq='1h'),'VesselType':[70]*3,'Status':[0]*3,'SOG':[10.,11.,12.],'COG':[260.,270.,280.],'LAT':[37.,37.01,37.02],'LON':[-76.,-76.01,-76.02]})
with contextlib.redirect_stdout(io.StringIO()): result=prepare(track)
actual=float(result.journey_duration.iloc[0]);reconstructed=float((result.distance/result.avg_speed).iloc[0])
checks['basic_target_reconstruction']={'target_hours':actual,'distance_divided_by_avg_speed_hours':reconstructed,'absolute_error':abs(actual-reconstructed)}
features=isolated_function((repo/'dashboard.py').read_text(encoding='utf8'),'create_enhanced_features_from_basic',{})
created=features(dict(n_points=100,speed_mean=10,speed_std=2,course_mean=359,course_std=2,distance=100,length=200,width=30,draft=9))
checks['dashboard_generated_feature_count']=len(created)
checks['dashboard_fixed_features']={k:created[k] for k in ['speed_efficiency','distance_efficiency','lat_std','lon_std','avg_hour','hour_variability','weekend_ratio','is_night_journey']}
checks['dashboard_derived_density']=created['trajectory_density']
checks['circular_course_example']={'angles':[359,1],'ordinary_mean':float(np.mean([359,1])),'correct_circular_mean_degrees':float(np.rad2deg(np.arctan2(np.sin(np.deg2rad([359,1])).mean(),np.cos(np.deg2rad([359,1])).mean()))%360)}
checks['full_grid']={'candidates':3**8,'folds':3,'cross_validation_fits':3**9}
allcode='\n'.join(''.join(c['source']) for c in notebook['cells'] if c['cell_type']=='code')
checks['isolation_forest_fit_present']='IsolationForest(' in allcode
checks['global_X_y_assignments']=[]
for index,cell in enumerate(notebook['cells']):
 if cell['cell_type']!='code':continue
 source=''.join(cell['source'])
 if source.startswith('pip ') or '!{' in source:continue
 for node in ast.parse(source).body:
  if isinstance(node,(ast.Assign,ast.AnnAssign)):
   targets=node.targets if isinstance(node,ast.Assign) else [node.target]
   for target in targets:
    if isinstance(target,ast.Name) and target.id in ['X','y']:checks['global_X_y_assignments'].append({'cell':index,'name':target.id})
checks['enhanced_class_call_requires_X_y']=True
checks['readme_mae_minutes']=.290*60
(root/'source_checks.json').write_text(json.dumps(checks,indent=2))
print(json.dumps(checks,indent=2))

