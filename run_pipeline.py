
import os
import sys
import asyncio
import traceback
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

LOG_FILE = os.path.join(BASE_DIR, "pipeline_run.log")

_log_fh = open(LOG_FILE, "w", encoding="utf-8", buffering=1)

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        _log_fh.write(line + "\n")
        _log_fh.flush()
    except Exception:
        pass

log("=== Pipeline Runner Started ===")

try:
    import scraper as scraper_module
    scraper_module.HEADLESS = True
    log(f"HEADLESS forced to: {scraper_module.HEADLESS}")

    from scraper import (
        scrape_google_maps,
        scrape_hotfrog,
        connect_to_google_sheets,
        SERVICE_ACCOUNT_KEY,
    )
    log("All imports OK")
except Exception as e:
    log(f"[IMPORT ERROR] {e}")
    traceback.print_exc(file=_log_fh)
    _log_fh.flush()
    _log_fh.close()
    sys.exit(1)


async def main():
    search_query = "top lead generation agencies in Pakistan"
    num_results = 5

    log(f"Search query: {search_query}")
    log(f"Results per source: {num_results}")

    worksheet = None
    try:
        if SERVICE_ACCOUNT_KEY and os.path.exists(SERVICE_ACCOUNT_KEY):
            log("Connecting to Google Sheets...")
            worksheet = connect_to_google_sheets()
            if worksheet:
                log("Google Sheets connection OK")
            else:
                log("Google Sheets: skipped (no worksheet)")
        else:
            log(f"[WARN] SERVICE_ACCOUNT_KEY: {SERVICE_ACCOUNT_KEY}")
    except Exception as e:
        log(f"[WARN] Sheets error: {e}")

    log("--- Phase 1: Google Maps Scrape ---")
    try:
        await scrape_google_maps(search_query, num_results, worksheet)
        log("Google Maps phase completed OK")
    except Exception as e:
        log(f"[ERROR] Google Maps scrape FAILED: {e}")
        traceback.print_exc(file=_log_fh)
        _log_fh.flush()

    log("--- Phase 2: Hotfrog Scrape ---")
    try:
        await scrape_hotfrog(search_query, num_results, worksheet)
        log("Hotfrog phase completed OK")
    except Exception as e:
        log(f"[ERROR] Hotfrog scrape FAILED: {e}")
        traceback.print_exc(file=_log_fh)
        _log_fh.flush()

    log("=== Pipeline COMPLETE ===")
    _log_fh.flush()
    _log_fh.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        log(f"[FATAL] Pipeline crashed: {e}")
        traceback.print_exc(file=_log_fh)
        _log_fh.flush()
        _log_fh.close()
        sys.exit(1)
