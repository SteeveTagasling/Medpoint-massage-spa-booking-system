import os
import sys

# We add the model code to website/models.py
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'medpoint.settings')
django.setup()

from django.core.management import call_command
try:
    print('Starting migrate...')
    call_command('migrate', 'website')
    print('Finished migrate')
except Exception as e:
    import traceback
    traceback.print_exc()

