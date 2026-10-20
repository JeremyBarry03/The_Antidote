# Let's analyze each aspect separately for better control

# 1. Vessel Types Analysis
print("Top 10 Vessel Types:")
print(df['VesselType'].value_counts().head(10))

# 2. Speed Analysis
print("\nSpeed Statistics:")
print(f"Average Speed (SOG): {df['SOG'].mean():.2f} knots")
print(f"Maximum Speed: {df['SOG'].max():.2f} knots")
print(f"Median Speed: {df['SOG'].median():.2f} knots")

# 3. Vessel Dimensions
print("\nVessel Dimensions Statistics:")
print("Length statistics:")
print(df['Length'].describe())
print("\nWidth statistics:")
print(df['Width'].describe())

# 4. Geographic Coverage
print("\nGeographic Coverage:")
print(f"Latitude range: {df['LAT'].min():.2f} to {df['LAT'].max():.2f}")
print(f"Longitude range: {df['LON'].min():.2f} to {df['LON'].max():.2f}")

# 5. Vessel Counts
print("\nVessel Counts:")
print(f"Number of unique vessels (MMSI): {df['MMSI'].nunique()}")

# 6. Status Distribution
print("\nVessel Status Distribution:")
status_dist = df['Status'].value_counts()
print(status_dist)

# Now let's create some basic plots
fig, axes = plt.subplots(2, 2, figsize=(15, 15))

# Plot 1: Speed Distribution
sns.histplot(data=df, x='SOG', bins=30, ax=axes[0,0])
axes[0,0].set_title('Speed Distribution')
axes[0,0].set_xlabel('Speed Over Ground (knots)')

# Plot 2: Top Vessel Types
df['VesselType'].value_counts().head(5).plot(kind='bar', ax=axes[0,1])
axes[0,1].set_title('Top 5 Vessel Types')
axes[0,1].tick_params(axis='x', rotation=45)

# Plot 3: Vessel Dimensions
axes[1,0].scatter(df['Length'], df['Width'], alpha=0.1)
axes[1,0].set_title('Vessel Dimensions')
axes[1,0].set_xlabel('Length')
axes[1,0].set_ylabel('Width')

# Plot 4: Geographic Distribution
axes[1,1].scatter(df['LON'], df['LAT'], alpha=0.1, s=1)
axes[1,1].set_title('Geographic Distribution')
axes[1,1].set_xlabel('Longitude')
axes[1,1].set_ylabel('Latitude')

plt.tight_layout()
plt.show()
