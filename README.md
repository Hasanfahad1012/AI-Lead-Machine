
# AI Lead Machine

A Python tool that scrapes Google Maps for business leads, extracts contact details (phone, website), crawls websites for emails, and saves everything to Google Sheets - with automated outreach, follow-ups, QuickEnrich email search, and Jina AI Reader for website content!

## Features

- Scrape Google Maps for businesses based on any search keyword
- Extract business name, phone number, and website
- **Jina AI Reader integration**: Fetch clean website content for personalization
- **QuickEnrich integration**: Domain search for verified decision-maker emails
- Crawl websites (homepage and contact pages) to extract email addresses
- Save all data automatically to Google Sheets
- **Automated outreach with personalized B2B emails** drafted by Gemini AI
- **SMTP integration** to send emails from your personal account
- **Cal.com booking link** included in all emails
- **Automated follow-up** after 48 hours if no meeting booked
- Uses free, open-source libraries (Playwright, BeautifulSoup)
- **Strict error handling**: Never crashes, skips failed steps and continues

## Setup Instructions

### 1. Install Dependencies

First, install the required Python packages:

```bash
pip install -r requirements.txt
```

Then, install Playwright browsers:

```bash
playwright install
```

### 2. Google Sheets Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable "Google Sheets API" and "Google Drive API"
4. Create a service account, download the JSON key file
5. Rename the key file to `service_account.json` and put it in this folder
6. Create a new Google Sheet and share it with your service account's email address (from the JSON key file)

### 3. QuickEnrich Setup

1. Go to [QuickEnrich](https://quickenrich.com/) and create an account (if needed)
2. Get your API Key from your QuickEnrich dashboard
3. Keep this key ready for your .env file

### 4. Configure All Environment Variables

Copy `.env.example` to `.env` and update all the values:

```
# Google Sheets Configuration
GOOGLE_SERVICE_ACCOUNT_KEY_PATH=./service_account.json
GOOGLE_SHEET_NAME=Your Google Sheet Name
GOOGLE_WORKSHEET_NAME=Sheet1

# Optional: Playwright Headless Mode
HEADLESS=true

# Google AI Studio Configuration (get from https://aistudio.google.com/app/apikey)
GEMINI_API_KEY=your_gemini_api_key_here

# QuickEnrich Configuration
QUICKENRICH_API_KEY=your_quickenrich_api_key_here

# Cal.com Configuration (your booking link)
CAL_LINK=https://cal.com/your-username/your-meeting

# SMTP Configuration (for your personal email)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password-here
SMTP_FROM_NAME=Your Name
```

#### How to get Gmail App Password:
1. Go to your Google Account
2. Under "Security" → enable "2-Step Verification"
3. Then create an "App Password" (search for it in your Google Account)
4. Use that as SMTP_PASSWORD

## Usage

### Scrape Leads and Send Initial Outreach

Run the scraper:

```bash
python scraper.py
```

Then, enter your search keyword and number of results to scrape! It will automatically:
1. Scrape Google Maps
2. Extract contact info
3. Use Jina AI Reader to fetch website content
4. Use QuickEnrich to search for verified decision-maker emails
5. Save leads to Google Sheets
6. Send personalized outreach emails (using website content to mention their specific services)

### Check and Send Follow-Up Emails

Run the follow-up script (can be scheduled with cron or task scheduler):

```bash
python followup.py
```

This checks Google Sheets and sends follow-up emails to any leads that haven't booked a meeting after 48 hours!

## Project Structure

```
AI lead machine/
├── .env.example       # Environment variables template
├── .gitignore         # Git ignore file
├── README.md          # This file!
├── requirements.txt   # Python dependencies
├── scraper.py         # Main scraping and initial outreach script
├── quickenrich.py         # QickEnrich domain search for verified emails 
├── outreach.py        # Gemini AI email drafting and SMTP sending
└── followup.py        # Follow-up email check and send script
```

