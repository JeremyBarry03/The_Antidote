# Read the CSV file with the correct parameters
df = pd.read_csv(file_name, 
                sep=',',  # File uses comma as separator
                encoding='utf-8',
                on_bad_lines='skip')  # Skip problematic lines

print("\nSuccessfully read the file. Here are the first few rows:")
display(df.head())

print("\nDataframe info:")
display(df.info())