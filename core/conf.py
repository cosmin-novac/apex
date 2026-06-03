import os

# Get the project root directory
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

PREPROC_FILENAME = os.path.join(DATA_DIR, "btc_data_preprocessed.csv")
PREPROC_OVERWRITE = False