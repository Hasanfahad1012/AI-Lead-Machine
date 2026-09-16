
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dateutil import parser

from outreach import send_follow_up

# Load environment variables
load_dotenv()

# Configuration
SERVICE_ACCOUNT_KEY = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY_PATH")
SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME")
WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME")


def connect_to_google_sheets():
    """Connect to Google Sheets and return worksheet."""
    try:
        if not SERVICE_ACCOUNT_KEY or not os.path.exists(SERVICE_ACCOUNT_KEY):
            print("[SKIPPED] Missing or invalid Google service account key")
            return None
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        credentials = ServiceAccountCredentials.from_json_keyfile_name(
            SERVICE_ACCOUNT_KEY, scope
        )
        client = gspread.authorize(credentials)
        sheet = client.open(SHEET_NAME)
        return sheet.worksheet(WORKSHEET_NAME)
    except Exception as e:
        print(f"[SKIPPED] Error connecting to Google Sheets: {e}")
        return None


def check_and_send_follow_ups():
    """Check Google Sheets and send follow-up emails after 48 hours."""
    worksheet = connect_to_google_sheets()
    if not worksheet:
        print("[SKIPPED] Google Sheets not available, stopping follow-up check")
        return

    try:
        all_rows = worksheet.get_all_records()
    except Exception as e:
        print(f"[SKIPPED] Error reading Google Sheets: {e}")
        return

    now = datetime.now()

    for i, row in enumerate(all_rows, start=2):  # Skip header row
        try:
            # Check if meeting already booked
            if row.get("Meeting Booked"):
                continue
            
            # Check if follow-up already sent
            if row.get("Follow Up Sent"):
                continue

            # Check if initial email was sent at least 48 hours ago
            initial_sent_str = row.get("Initial Email Sent")
            if not initial_sent_str:
                continue

            initial_sent = parser.isoparse(initial_sent_str)
            if now - initial_sent >= timedelta(hours=48):
                # Send follow-up
                lead = {
                    "name": row["Business Name"],
                    "phone": row["Phone Number"],
                    "website": row["Website"],
                    "emails": row["Emails"].split(", ") if row.get("Emails") else []
                }
                print(f"Sending follow-up to {lead['name']}...")
                follow_up_success = send_follow_up(lead)
                
                # Update sheet
                if follow_up_success:
                    worksheet.update_cell(i, 7, datetime.now().isoformat())  # Follow Up Sent
                    worksheet.update_cell(i, 5, "Follow Up Sent")  # Status
                    print(f"Follow-up sent to {lead['name']}!")
                else:
                    worksheet.update_cell(i, 5, "Follow Up Failed")
                    print(f"Failed to send follow-up to {lead['name']}")
        
        except Exception as e:
            print(f"[SKIPPED] Error processing row {i}: {e}")


if __name__ == "__main__":
    check_and_send_follow_ups()

