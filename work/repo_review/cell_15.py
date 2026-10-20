# IMPROVED ETA PREDICTION MODEL WITH ENHANCED XGBOOST
# =====================================================

# Import all required libraries
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split, GridSearchCV, cross_val_score, TimeSeriesSplit
from sklearn.preprocessing import StandardScaler, RobustScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.ensemble import IsolationForest
import joblib
import warnings
import matplotlib.pyplot as plt
import seaborn as sns

# Suppress warnings for cleaner output
warnings.filterwarnings('ignore')

print("🚢 ENHANCED ETA PREDICTION MODEL")
print("=" * 50)
print("✅ All required libraries imported successfully!")
