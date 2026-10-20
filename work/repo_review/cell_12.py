# Function to predict ETA for new vessel data
def predict_eta(model, vessel_data):
    """
    Predict ETA for a new vessel journey
    
    Parameters:
    - model: trained XGBoost model
    - vessel_data: dictionary containing:
        - points_count: number of AIS points
        - mean_speed: average speed
        - std_speed: standard deviation of speed
        - mean_course: average course
        - std_course: standard deviation of course
        - distance: journey distance in km
        - avg_speed: average speed for the journey
    
    Returns:
    - predicted journey duration in hours
    """
    # Create a DataFrame with the required features
    features = pd.DataFrame([vessel_data])
    
    # Make prediction
    predicted_duration = model.predict(features)[0]
    
    return predicted_duration

# Example usage
example_vessel = {
    'points_count': 100,
    'mean_speed': 12,
    'std_speed': 2,
    'mean_course': 180,
    'std_course': 10,
    'distance': 500,
    'avg_speed': 12
}

predicted_duration = predict_eta(model, example_vessel)
print(f"\nExample ETA Prediction:")
print(f"Vessel traveling {example_vessel['distance']:.1f} km at {example_vessel['mean_speed']:.1f} knots")
print(f"Predicted journey duration: {predicted_duration:.2f} hours")
