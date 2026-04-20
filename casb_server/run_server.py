import sys
import os

# Always resolve paths relative to this file's location
# so it works from any directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from waitress import serve
from app import app

print('=' * 55)
print('  CASB Results Server starting on port 4012...')
print(f'  Serving from: {os.path.dirname(os.path.abspath(__file__))}')
print('=' * 55)

serve(app, host='0.0.0.0', port=4012)