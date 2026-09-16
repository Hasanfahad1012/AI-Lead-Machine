
import os
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials

load_dotenv()

SERVICE_ACCOUNT_KEY = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY_PATH")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME")

print(f"SERVICE_ACCOUNT_KEY: {SERVICE_ACCOUNT_KEY}")
print(f"File exists: {os.path.exists(SERVICE_ACCOUNT_KEY)}")
print(f"SHEET_ID: {SHEET_ID}")
print(f"WORKSHEET_NAME: {WORKSHEET_NAME}")

try:
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    credentials = ServiceAccountCredentials.from_json_keyfile_name(
        SERVICE_ACCOUNT_KEY, scope
    )
    client = gspread.authorize(credentials)
    print("Successfully authorized with Google!")
    sheet = client.open_by_key(SHEET_ID)
    print(f"Successfully opened sheet with ID: {SHEET_ID}")
    worksheet = sheet.worksheet(WORKSHEET_NAME)
    print(f"Successfully opened worksheet: {WORKSHEET_NAME}")
    print("Test passed!")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
