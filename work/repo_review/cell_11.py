# Prepare features and target for the model
def prepare_model_data(trajectory_features):
    # Features to use for prediction
    feature_columns = [
        'points_count', 'mean_speed', 'std_speed',
        'mean_course', 'std_course', 'distance',
        'avg_speed'
    ]
    
    X = trajectory_features[feature_columns]
    y = trajectory_features['journey_duration']
    
    # Split the data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    
    return X_train, X_test, y_train, y_test, feature_columns

# Train XGBoost model
def train_xgboost_model(X_train, y_train, X_test, y_test):
    # Initialize XGBoost model
    model = xgb.XGBRegressor(
        objective='reg:squarederror',
        n_estimators=100,
        learning_rate=0.1,
        max_depth=6,
        random_state=42,
        tree_method='hist',  # Use histogram-based algorithm for faster training
        enable_categorical=False  # Disable categorical feature support
    )
    
    # Train the model
    print("Training XGBoost model...")
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],  # Only use test set for evaluation
        verbose=True
    )
    
    # Make predictions
    y_pred = model.predict(X_test)
    
    # Calculate metrics
    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    
    print("\nModel Performance:")
    print(f"Mean Absolute Error: {mae:.2f} hours")
    print(f"Root Mean Squared Error: {rmse:.2f} hours")
    
    # Feature importance
    importance = pd.DataFrame({
        'feature': feature_columns,
        'importance': model.feature_importances_
    })
    importance = importance.sort_values('importance', ascending=False)
    
    print("\nFeature Importance:")
    print(importance)
    
    return model, importance

# Prepare and train the model
X_train, X_test, y_train, y_test, feature_columns = prepare_model_data(trajectory_features)

# Convert data to float32 to reduce memory usage and improve performance
X_train = X_train.astype('float32')
X_test = X_test.astype('float32')
y_train = y_train.astype('float32')
y_test = y_test.astype('float32')

model, feature_importance = train_xgboost_model(X_train, y_train, X_test, y_test)

# Visualize feature importance
plt.figure(figsize=(10, 6))
sns.barplot(x='importance', y='feature', data=feature_importance)
plt.title('Feature Importance in ETA Prediction')
plt.xlabel('Importance Score')
plt.tight_layout()
plt.show()

# Example predictions
print("\nExample Predictions:")
example_data = X_test.head(5)
predictions = model.predict(example_data)
actual_values = y_test.iloc[:5]

comparison = pd.DataFrame({
    'Actual Duration (hours)': actual_values,
    'Predicted Duration (hours)': predictions,
    'Absolute Error (hours)': abs(actual_values - predictions)
})
print(comparison.round(2))

# Prepare and train the model
X_train, X_test, y_train, y_test, feature_columns = prepare_model_data(trajectory_features)
model, feature_importance = train_xgboost_model(X_train, y_train, X_test, y_test)

# Visualize feature importance
plt.figure(figsize=(10, 6))
sns.barplot(x='importance', y='feature', data=feature_importance)
plt.title('Feature Importance in ETA Prediction')
plt.xlabel('Importance Score')
plt.tight_layout()
plt.show()

# Example predictions
print("\nExample Predictions:")
example_data = X_test.head(5)
predictions = model.predict(example_data)
actual_values = y_test.iloc[:5]

comparison = pd.DataFrame({
    'Actual Duration (hours)': actual_values,
    'Predicted Duration (hours)': predictions,
    'Absolute Error (hours)': abs(actual_values - predictions)
})
print(comparison.round(2))

# Prepare and train the model
X_train, X_test, y_train, y_test, feature_columns = prepare_model_data(trajectory_features)
model, feature_importance = train_xgboost_model(X_train, y_train, X_test, y_test)

# Visualize feature importance
plt.figure(figsize=(10, 6))
sns.barplot(x='importance', y='feature', data=feature_importance)
plt.title('Feature Importance in ETA Prediction')
plt.xlabel('Importance Score')
plt.tight_layout()
plt.show()

# Example predictions
print("\nExample Predictions:")
example_data = X_test.head(5)
predictions = model.predict(example_data)
actual_values = y_test.iloc[:5]

comparison = pd.DataFrame({
    'Actual Duration (hours)': actual_values,
    'Predicted Duration (hours)': predictions,
    'Absolute Error (hours)': abs(actual_values - predictions)
})
print(comparison.round(2))
