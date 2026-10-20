# Import necessary libraries for analysis
import seaborn as sns
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime

# Set basic plot style
plt.style.use('default')
sns.set_theme()  # Use seaborn's default theme

# Basic information about the dataset
print("Dataset Overview:")
print("-----------------")
print(f"Number of rows: {len(df)}")
print(f"Number of columns: {len(df.columns)}")
print("\nColumns in the dataset:")
for col in df.columns:
    print(f"- {col}")

# Display basic statistics
print("\nBasic Statistics:")
print(df.describe(include='all'))
