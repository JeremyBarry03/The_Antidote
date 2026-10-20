
class EnhancedETAPredictor:
    def __init__(self):
        self.model = None
        self.scaler = None
        self.feature_names = None
        self.best_params = None
        
    def train_model(self, X, y, use_hyperparameter_tuning=True):
        """
        Train an advanced XGBoost model with optional hyperparameter tuning
        """
        print("🚀 Training Enhanced XGBoost ETA Prediction Model")
        print("=" * 55)
        
        # Split the data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=None
        )
        
        # Scale features for better performance
        print("📊 Scaling features...")
        self.scaler = RobustScaler()  # More robust to outliers than StandardScaler
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)
        
        if use_hyperparameter_tuning:
            print("🔧 Performing hyperparameter tuning...")
            
            # Define parameter grid for tuning
            param_grid = {
                'n_estimators': [200, 300, 400],
                'learning_rate': [0.05, 0.1, 0.15],
                'max_depth': [4, 6, 8],
                'min_child_weight': [1, 3, 5],
                'subsample': [0.8, 0.9, 1.0],
                'colsample_bytree': [0.8, 0.9, 1.0],
                'reg_alpha': [0, 0.1, 0.5],
                'reg_lambda': [0.1, 1, 2]
            }
            
            # Base model
            base_model = xgb.XGBRegressor(
                objective='reg:squarederror',
                random_state=42,
                tree_method='hist',
                n_jobs=-1
            )
            
            # Use TimeSeriesSplit for cross-validation (better for temporal data)
            cv = TimeSeriesSplit(n_splits=3)
            
            # Grid search with cross-validation
            grid_search = GridSearchCV(
                base_model,
                param_grid,
                cv=cv,
                scoring='neg_mean_absolute_error',
                n_jobs=-1,
                verbose=1
            )
            
            grid_search.fit(X_train_scaled, y_train)
            
            # Get best model
            self.model = grid_search.best_estimator_
            self.best_params = grid_search.best_params_
            
            print(f"✅ Best parameters found: {self.best_params}")
            print(f"✅ Best CV score: {-grid_search.best_score_:.4f} MAE")
            
        else:
            print("🔧 Using default optimized parameters...")
            # Use well-tuned default parameters
            self.model = xgb.XGBRegressor(
                objective='reg:squarederror',
                n_estimators=300,
                learning_rate=0.1,
                max_depth=6,
                min_child_weight=3,
                subsample=0.9,
                colsample_bytree=0.9,
                reg_alpha=0.1,
                reg_lambda=1,
                random_state=42,
                tree_method='hist',
                n_jobs=-1
            )
            
            # Train the model (FIXED: removed early_stopping_rounds for XGBoost compatibility)
            self.model.fit(
                X_train_scaled, y_train,
                eval_set=[(X_test_scaled, y_test)],
                verbose=False
            )
        
        # Make predictions
        y_pred_train = self.model.predict(X_train_scaled)
        y_pred_test = self.model.predict(X_test_scaled)
        
        # Calculate comprehensive metrics
        metrics = self._calculate_metrics(y_train, y_pred_train, y_test, y_pred_test)
        
        # Store feature names
        self.feature_names = X.columns.tolist()
        
        return metrics
    
    def _calculate_metrics(self, y_train, y_pred_train, y_test, y_pred_test):
        """Calculate comprehensive evaluation metrics"""
        
        # Training metrics
        train_mae = mean_absolute_error(y_train, y_pred_train)
        train_rmse = np.sqrt(mean_squared_error(y_train, y_pred_train))
        train_r2 = r2_score(y_train, y_pred_train)
        
        # Test metrics
        test_mae = mean_absolute_error(y_test, y_pred_test)
        test_rmse = np.sqrt(mean_squared_error(y_test, y_pred_test))
        test_r2 = r2_score(y_test, y_pred_test)
        
        # Calculate percentage errors
        test_mape = np.mean(np.abs((y_test - y_pred_test) / y_test)) * 100
        
        metrics = {
            'train_mae': train_mae,
            'train_rmse': train_rmse,
            'train_r2': train_r2,
            'test_mae': test_mae,
            'test_rmse': test_rmse,
            'test_r2': test_r2,
            'test_mape': test_mape
        }
        
        # Print results
        print(f"\n📊 MODEL PERFORMANCE RESULTS")
        print("=" * 40)
        print(f"Training MAE:     {train_mae:.3f} hours")
        print(f"Training RMSE:    {train_rmse:.3f} hours")
        print(f"Training R²:      {train_r2:.4f}")
        print(f"")
        print(f"Test MAE:         {test_mae:.3f} hours")
        print(f"Test RMSE:        {test_rmse:.3f} hours")
        print(f"Test R²:          {test_r2:.4f}")
        print(f"Test MAPE:        {test_mape:.2f}%")
        
        return metrics
    
    def get_feature_importance(self):
        """Get feature importance from the trained model"""
        if self.model is None:
            raise ValueError("Model not trained yet!")
        
        importance_df = pd.DataFrame({
            'feature': self.feature_names,
            'importance': self.model.feature_importances_
        }).sort_values('importance', ascending=False)
        
        return importance_df
    
    def predict(self, X):
        """Make predictions with the trained model"""
        if self.model is None:
            raise ValueError("Model not trained yet!")
        if self.scaler is None:
            raise ValueError("Scaler not initialized!")
        
        X_scaled = self.scaler.transform(X)
        return self.model.predict(X_scaled)
    
    def save_model(self, filename):
        """Save the trained model and scaler"""
        if self.model is None:
            raise ValueError("Model not trained yet!")
        
        model_data = {
            'model': self.model,
            'scaler': self.scaler,
            'feature_names': self.feature_names,
            'best_params': self.best_params
        }
        
        joblib.dump(model_data, filename)
        print(f"✅ Model saved as {filename}")
    
    def load_model(self, filename):
        """Load a trained model and scaler"""
        model_data = joblib.load(filename)
        
        self.model = model_data['model']
        self.scaler = model_data['scaler']
        self.feature_names = model_data['feature_names']
        self.best_params = model_data.get('best_params', None)
        
        print(f"✅ Model loaded from {filename}")

# Initialize and train the enhanced model with fixed XGBoost compatibility
enhanced_eta_model = EnhancedETAPredictor()
training_metrics = enhanced_eta_model.train_model(X, y, use_hyperparameter_tuning=False)  # Set to True for full tuning

print(f"\n🎯 ENHANCED MODEL SUMMARY:")
print(f"=" * 40)
print(f"• Total Features:          {len(X.columns)}")
print(f"• Training Samples:        {len(X)}")

# Save the enhanced model
enhanced_eta_model.save_model('enhanced_eta_model.joblib')
print(f"\n💾 Enhanced model saved as 'enhanced_eta_model.joblib'")
