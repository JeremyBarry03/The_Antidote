# ENHANCED FEATURE ENGINEERING FOR MARITIME ETA PREDICTION
# =========================================================

def create_advanced_maritime_features(df):
    """
    Create comprehensive features for maritime ETA prediction
    """
    print("📊 Creating advanced maritime features...")
    
    # Create a copy
    df_enhanced = df.copy()
    
    # Convert BaseDateTime to datetime
    df_enhanced['BaseDateTime'] = pd.to_datetime(df_enhanced['BaseDateTime'])
    
    # Time-based features
    df_enhanced['Hour'] = df_enhanced['BaseDateTime'].dt.hour
    df_enhanced['DayOfWeek'] = df_enhanced['BaseDateTime'].dt.dayofweek
    df_enhanced['IsWeekend'] = (df_enhanced['DayOfWeek'] >= 5).astype(int)
    df_enhanced['TimeOfDay'] = pd.cut(df_enhanced['Hour'], 
                                     bins=[0, 6, 12, 18, 24], 
                                     labels=['Night', 'Morning', 'Afternoon', 'Evening'])
    
    # Group by MMSI to create vessel journey features
    print("🔄 Aggregating vessel trajectories...")
    
    vessel_features = df_enhanced.groupby('MMSI').agg({
        'BaseDateTime': ['count', 'min', 'max'],
        'SOG': ['mean', 'std', 'min', 'max', 'median', lambda x: x.quantile(0.75), lambda x: x.quantile(0.25)],
        'COG': ['mean', 'std', 'min', 'max', lambda x: np.ptp(x)],  # Peak-to-peak (range)
        'Heading': ['mean', 'std', lambda x: x.count()],
        'LAT': ['min', 'max', 'mean', 'std'],
        'LON': ['min', 'max', 'mean', 'std'],
        'VesselType': 'first',
        'Status': lambda x: x.mode().iloc[0] if not x.mode().empty else x.iloc[0],  # Most common status
        'Length': 'first',
        'Width': 'first',
        'Draft': 'first',
        'Hour': ['mean', 'std'],
        'DayOfWeek': lambda x: x.mode().iloc[0] if not x.mode().empty else x.iloc[0],
        'IsWeekend': 'mean'
    }).reset_index()
    
    # Flatten column names
    vessel_features.columns = [
        'MMSI', 'n_points', 'start_time', 'end_time',
        'speed_mean', 'speed_std', 'speed_min', 'speed_max', 'speed_median', 'speed_q75', 'speed_q25',
        'course_mean', 'course_std', 'course_min', 'course_max', 'course_range',
        'heading_mean', 'heading_std', 'heading_count',
        'lat_min', 'lat_max', 'lat_mean', 'lat_std',
        'lon_min', 'lon_max', 'lon_mean', 'lon_std',
        'vessel_type', 'status_mode', 'length', 'width', 'draft',
        'hour_mean', 'hour_std', 'day_mode', 'weekend_ratio'
    ]
    
    return vessel_features

# Create enhanced features
enhanced_features = create_advanced_maritime_features(df)
print(f"✅ Created features for {len(enhanced_features)} vessel trajectories")
