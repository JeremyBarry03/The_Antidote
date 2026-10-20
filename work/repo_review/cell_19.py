# TROUBLESHOOTING AND QUICK FIX
# =============================

# If you encounter import errors, run this cell first
try:
    # Test all required imports
    import numpy as np
    import pandas as pd
    import xgboost as xgb
    from sklearn.model_selection import train_test_split, GridSearchCV, TimeSeriesSplit
    from sklearn.preprocessing import StandardScaler, RobustScaler
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    from sklearn.ensemble import IsolationForest
    import joblib
    import matplotlib.pyplot as plt
    import seaborn as sns
    
    print("✅ All imports successful!")
    print("✅ You can now run the enhanced model cells")
    
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("📥 Please install missing packages:")
    print("   pip install xgboost scikit-learn matplotlib seaborn")

# Quick model training function (simplified version)
def train_quick_enhanced_model(X, y):
    """Quick version without hyperparameter tuning for testing"""
    
    print("🚀 Training Quick Enhanced Model...")
    
    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    # Scale features
    scaler = RobustScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Train XGBoost
    model = xgb.XGBRegressor(
        objective='reg:squarederror',
        n_estimators=100,  # Reduced for speed
        learning_rate=0.1,
        max_depth=6,
        random_state=42,
        tree_method='hist'
    )
    
    model.fit(X_train_scaled, y_train, verbose=False)
    
    # Evaluate
    y_pred = model.predict(X_test_scaled)
    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    r2 = r2_score(y_test, y_pred)
    
    print(f"✅ Quick Model Results:")
    print(f"   MAE:  {mae:.3f} hours")
    print(f"   RMSE: {rmse:.3f} hours")
    print(f"   R²:   {r2:.4f}")
    
    return model, scaler

print("🛠️  Troubleshooting tools ready!")
print("💡 If you encounter errors, try running this cell first")
