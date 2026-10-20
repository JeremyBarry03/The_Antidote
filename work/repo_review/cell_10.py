# Import necessary libraries
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import mean_absolute_error, mean_squared_error
import numpy as np

# Create features for ETA prediction
def prepare_data_for_eta(df):
    # Create a copy of the dataframe
    df_eta = df.copy()
    
    # Convert BaseDateTime to datetime if not already
    df_eta['BaseDateTime'] = pd.to_datetime(df_eta['BaseDateTime'])
    
    # Extract time-based features
    df_eta['Hour'] = df_eta['BaseDateTime'].dt.hour
    df_eta['Day'] = df_eta['BaseDateTime'].dt.day
    df_eta['DayOfWeek'] = df_eta['BaseDateTime'].dt.dayofweek
    
    # Convert categorical variables
    le = LabelEncoder()
    df_eta['VesselType'] = le.fit_transform(df_eta['VesselType'].astype(str))
    df_eta['Status'] = le.fit_transform(df_eta['Status'].astype(str))
    
    # Group by MMSI to create trajectory features
    trajectory_features = df_eta.groupby('MMSI').agg({
        'BaseDateTime': ['count', 'min', 'max'],
        'SOG': ['mean', 'std'],
        'COG': ['mean', 'std'],
        'LAT': ['min', 'max'],
        'LON': ['min', 'max']
    }).reset_index()
    
    # Flatten column names
    trajectory_features.columns = ['MMSI', 'points_count', 'start_time', 'end_time',
                                 'mean_speed', 'std_speed', 'mean_course', 'std_course',
                                 'min_lat', 'max_lat', 'min_lon', 'max_lon']
    
    # Calculate journey duration in hours
    trajectory_features['journey_duration'] = (
        trajectory_features['end_time'] - trajectory_features['start_time']
    ).dt.total_seconds() / 3600
    
    # Vectorized haversine distance calculation
    def haversine_distance_vectorized(df):
        R = 6371  # Earth's radius in kilometers
        
        # Convert decimal degrees to radians
        lat1 = np.radians(df['min_lat'])
        lon1 = np.radians(df['min_lon'])
        lat2 = np.radians(df['max_lat'])
        lon2 = np.radians(df['max_lon'])
        
        # Haversine formula
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
        c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))
        distance = R * c
        
        return distance
    
    # Calculate distances
    trajectory_features['distance'] = haversine_distance_vectorized(trajectory_features)
    
    # Calculate average speed from distance and duration
    trajectory_features['avg_speed'] = trajectory_features['distance'] / trajectory_features['journey_duration']
    
    # Remove rows with invalid values
    trajectory_features = trajectory_features.replace([np.inf, -np.inf], np.nan).dropna()
    
    print("Data preparation completed.")
    print(f"Number of trajectories: {len(trajectory_features)}")
    
    return trajectory_features

# Prepare the data
trajectory_features = prepare_data_for_eta(df)

# Display the first few rows and basic statistics
print("\nFirst few rows of prepared data:")
display(trajectory_features.head())

print("\nBasic statistics of the features:")
display(trajectory_features.describe())

# Prepare the data
trajectory_features = prepare_data_for_eta(df)

# Display the first few rows and basic statistics
print("\nFirst few rows of prepared data:")
display(trajectory_features.head())

print("\nBasic statistics of the features:")
display(trajectory_features.describe())
