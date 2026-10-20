# Temporal analysis
print("Temporal Analysis:")
print("-----------------")

# Extract time components
df['Hour'] = df['BaseDateTime'].dt.hour
df['Day'] = df['BaseDateTime'].dt.day

# Print time range
print(f"\nTime range of data:")
print(f"Start: {df['BaseDateTime'].min()}")
print(f"End: {df['BaseDateTime'].max()}")

# Hourly statistics
print("\nHourly Activity Summary:")
hourly_stats = df.groupby('Hour').agg({
    'MMSI': 'count',
    'SOG': 'mean'
}).round(2)
hourly_stats.columns = ['Number of Records', 'Average Speed']
print(hourly_stats)

# Summary by vessel type
print("\nVessel Type Summary (Top 10):")
vessel_summary = df.groupby('VesselType').agg({
    'MMSI': 'count',
    'SOG': 'mean',
    'Length': 'mean',
    'Width': 'mean'
}).round(2)
vessel_summary.columns = ['Count', 'Avg Speed', 'Avg Length', 'Avg Width']
print(vessel_summary.sort_values('Count', ascending=False).head(10))

# Create simple plots for temporal patterns
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 5))

# Activity by hour
df['Hour'].value_counts().sort_index().plot(kind='bar', ax=ax1)
ax1.set_title('Vessel Activity by Hour')
ax1.set_xlabel('Hour of Day')
ax1.set_ylabel('Number of Records')

# Average speed by hour
df.groupby('Hour')['SOG'].mean().plot(kind='line', marker='o', ax=ax2)
ax2.set_title('Average Speed by Hour')
ax2.set_xlabel('Hour of Day')
ax2.set_ylabel('Average Speed (knots)')

plt.tight_layout()
plt.show()
