
import os
import sys
import asyncio
from dotenv import load_dotenv

# Import our modules — now includes scrape_hotfrog alongside Google Maps
from scraper import scrape_google_maps, scrape_hotfrog, connect_to_google_sheets

# Load environment variables
load_dotenv()


async def main():
    # Get search query from command-line arguments
    if len(sys.argv) < 2:
        print("Usage: python main.py <search_query> [num_results]")
        print("Example: python main.py \"wifi installers in los angeles\" 10")
        sys.exit(1)

    search_query = sys.argv[1]
    num_results = 20
    if len(sys.argv) >= 3:
        try:
            num_results = int(sys.argv[2])
        except ValueError:
            print("[WARNING] Invalid number of results, using default (20)")
            num_results = 20

    print(f"Starting full pipeline for search query: {search_query}")
    print(f"Number of results to scrape PER SOURCE: {num_results}")
    print(f"Total max leads (Google Maps + Hotfrog): {num_results * 2}")

    # Step 1: Connect to Google Sheets first
    print("\n[1/5] Connecting to Google Sheets...")
    worksheet = connect_to_google_sheets()

    # Step 2: Scrape Google Maps and save each lead immediately
    print("\n[2/5] Scraping Google Maps and processing leads...")
    await scrape_google_maps(search_query, num_results, worksheet)

    # Step 3: Scrape Hotfrog (free directory source) with anti-bot delays
    print("\n[3/5] Scraping Hotfrog and processing leads...")
    await scrape_hotfrog(search_query, num_results, worksheet)

    print("\n[4/5] Pipeline complete! Both Google Maps and Hotfrog sources processed.")
    print("\n[5/5] Next steps: Run 'python followup.py' after 48 hours to send follow-ups.")


if __name__ == "__main__":
    asyncio.run(main())
