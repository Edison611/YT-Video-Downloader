import os
import sys

# Make the top-level modules (main, drive_upload) importable from tests/.
sys.path.insert(0, os.path.dirname(__file__))
