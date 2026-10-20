
import pandas as pd

# First, let's examine the file structure

# Read the first few lines to check the format
print("First few lines of the file:")
with open(file_name, 'r') as f:
    for i, line in enumerate(f):
        print(line.strip())
        if i >= 4:
            break

