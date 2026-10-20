# Convert data types
df['BaseDateTime'] = pd.to_datetime(df['BaseDateTime'])

# Convert numeric columns
numeric_columns = ['LAT', 'LON', 'SOG', 'COG', 'Heading', 'Length', 'Width', 'Draft']
for col in numeric_columns:
    df[col] = pd.to_numeric(df[col], errors='coerce')

# Analyze missing values
print("Missing Values Analysis:")
print("----------------------")
missing_values = df.isnull().sum()
missing_percentage = (missing_values / len(df)) * 100
missing_info = pd.DataFrame({
    'Missing Values': missing_values,
    'Percentage': missing_percentage
})
print(missing_info)

# Time analysis
print("\nTime Range Analysis:")
print("------------------")
print(f"Start Date: {df['BaseDateTime'].min()}")
print(f"End Date: {df['BaseDateTime'].max()}")
print(f"Time Span: {df['BaseDateTime'].max() - df['BaseDateTime'].min()}")
