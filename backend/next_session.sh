#!/bin/bash
cd ~/PycharmProjects/iftr/backend
source .venv/bin/activate

echo "=== Quick Import Test ==="
python -c "
import sys
print(f'Python: {sys.executable}')

# Test core imports
from app.models.order import Order
from app.models.driver import Driver
from app.core.encryption import encrypt_data
print('✅ Core imports work')

# Quick encryption test
test = 'hello'
enc = encrypt_data(test)
print(f'✅ Encryption works: {enc[:20]}...')
"

echo -e "\n=== Model Files Status ==="
ls -la app/models/*.py | awk '{print $9, "(" $5 " bytes)"}'

echo -e "\n=== Ready for model restoration! ==="
