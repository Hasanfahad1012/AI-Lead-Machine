
import sys
import traceback

try:
    print("Starting test...", flush=True)
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f"Working dir: {os.getcwd()}", flush=True)
    print("Importing scraper...", flush=True)
    import scraper
    print("scraper imported OK", flush=True)
    print(f"SERVICE_ACCOUNT_KEY path: {scraper.SERVICE_ACCOUNT_KEY}", flush=True)
    print(f"Key exists: {os.path.exists(scraper.SERVICE_ACCOUNT_KEY) if scraper.SERVICE_ACCOUNT_KEY else 'None'}", flush=True)
except Exception as e:
    print(f"ERROR: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)
