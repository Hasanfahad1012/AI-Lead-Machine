
import os
import re
import time
import asyncio
import random
import urllib.parse as up
from datetime import datetime
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import requests

# Import our modules
from outreach import (
    send_email,
    draft_email,
    looks_like_placeholder_email,
    send_initial_outreach,
)

# Load environment variables
load_dotenv()

# Configuration
SERVICE_ACCOUNT_KEY = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY_PATH")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME")
HEADLESS = True

# Email regex pattern
EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

# Common contact page paths
CONTACT_PATHS = ["/contact", "/contact-us"]
ABOUT_PATHS = ["/about", "/about-us", "/aboutus"]


def safe_print(text):
    """Print text safely on Windows cp1252 consoles — drop/replace unprintable chars."""
    try:
        print(text)
    except UnicodeEncodeError:
        cleaned = text.encode("cp1252", errors="replace").decode("cp1252", errors="replace")
        print(cleaned)
    except Exception:
        try:
            print(text.encode("ascii", errors="replace").decode("ascii"))
        except Exception:
            pass


def sanitize_for_console(text):
    """Remove Material Icons / private-use Unicode chars that break Windows console output."""
    if not text:
        return text
    cleaned = "".join(ch if ord(ch) < 0xE000 or ord(ch) > 0xF8FF else " " for ch in text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


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
        sheet = client.open_by_key(SHEET_ID)
        return sheet.worksheet(WORKSHEET_NAME)
    except Exception as e:
        print(f"[SKIPPED] Error connecting to Google Sheets: {e}")
        return None


CANONICAL_HEADERS = [
    "Business Name", "Phone Number", "Website", "Emails",
    "Pitch", "Status", "Source",
    "Initial Email Sent", "Follow Up Sent", "Meeting Booked"
]


def _ensure_headers(worksheet):
    """Ensure the worksheet has the canonical header row, including 'Source' column."""
    if not worksheet:
        return
    try:
        existing_headers = worksheet.row_values(1)
        if not existing_headers:
            worksheet.append_row(CANONICAL_HEADERS)
            return
        if "Source" not in existing_headers:
            try:
                pos = 6
                for idx, h in enumerate(existing_headers):
                    if h.strip().lower() == "status":
                        pos = idx + 1
                        break
                existing_headers.insert(pos, "Source")
                worksheet.insert_row(existing_headers, 1)
            except Exception:
                pass
    except Exception:
        pass


def save_single_lead_to_sheet(worksheet, lead):
    """Save a single lead to Google Sheets, routing Hotfrog description into Gemini context."""
    if not worksheet:
        return False

    try:
        _ensure_headers(worksheet)

        # Duplicate check
        try:
            existing_cells = worksheet.findall(lead["name"])
            if existing_cells:
                return False
        except Exception:
            pass

        initial_email_sent = ""
        pitch = "N/A"
        status = "No Email Found"
        source = sanitize_for_console(lead.get("source", "Unknown"))
        gemini_used_fallback = False
        gemini_reason = None

        if lead.get("emails"):
            # Seed with directory description if available
            hotfrog_desc = sanitize_for_console(lead.get("description", "") or "").strip()
            company_ctx = lead.get("website_content", "") or ""
            if hotfrog_desc and len(hotfrog_desc) > 10:
                company_ctx = (
                    f"Directory listing description: {hotfrog_desc}\n\n"
                    f"Website content: {company_ctx}"
                ).strip()
            if not company_ctx and lead.get("website") and lead["website"] != "N/A":
                try:
                    company_ctx = asyncio.run(fetch_company_context(lead["website"]))
                except Exception:
                    pass

            lead_for_draft = {
                "name": lead["name"],
                "website": lead.get("website", "N/A"),
                "phone": lead.get("phone", "N/A"),
                "website_content": company_ctx
            }

            # Verification prints
            safe_print(f"  [VERIFY] Generating for: {lead['name']} (Source: {source}) | {lead.get('website', 'N/A')}")
            if company_ctx:
                safe_print(f"  [VERIFY] Context snippet: {sanitize_for_console(company_ctx[:200]).replace(chr(10),' ')}...")

            # Consume new tuple output so we can tag the Status column
            pitch, gemini_used_fallback, gemini_reason = draft_email(lead_for_draft, is_follow_up=False)

            initial_email_sent = datetime.now().isoformat()
            outreach_success = False
            try:
                outreach_success = send_initial_outreach({**lead, "website_content": company_ctx})
            except Exception:
                if isinstance(lead.get("emails"), list) and lead["emails"]:
                    target_email = lead["emails"][0]
                    if not looks_like_placeholder_email(target_email):
                        outreach_success = send_email(
                            target_email,
                            f"Quick question about {lead['name']}",
                            pitch,
                        )
            if outreach_success:
                if gemini_used_fallback and (gemini_reason and "429" in str(gemini_reason).lower() or "quota" in str(gemini_reason).lower()):
                    # User-requested explicit Status note
                    status = "Sent (Gemini API Maxed - Used Fallback Template)"
                elif gemini_used_fallback:
                    status = "Sent (Non-AI Fallback Template)"
                else:
                    status = "Sent"
            else:
                status = "Outreach Failed"

        # Build and append row
        emails_raw = lead.get("emails") or []
        if isinstance(emails_raw, list):
            emails_str = ", ".join(emails_raw) if emails_raw else "N/A"
        else:
            emails_str = emails_raw if emails_raw else "N/A"
        row_data = [
            lead["name"],
            lead.get("phone", "N/A"),
            lead.get("website", "N/A"),
            emails_str,
            pitch,
            status,
            source,
            initial_email_sent,
            "",
            ""
        ]
        worksheet.append_row(row_data)
        safe_print(f"  [SHEETS SUCCESS] Recorded {lead['name']} (Source: {source}) | Status: {status}")
        return True

    except Exception as e:
        safe_print(f"[SHEETS ERROR] Failed to record in Google Sheets: {e}")
        import traceback
        traceback.print_exc()
        return False


def extract_and_filter_emails(html_content):
    """Extract emails from HTML, then filter out junk + demo placeholder addresses."""
    all_emails = EMAIL_PATTERN.findall(html_content or "")

    junk_patterns = [
        "sentry", "wixpress", "bootstrap", "schema.org",
        ".png", ".jpg", ".jpeg", ".svg", ".gif",
        "example.com", "test.com", "dummy.com"
    ]

    filtered_emails = []
    for email in all_emails:
        email_lower = email.lower()
        is_junk = any(pattern in email_lower for pattern in junk_patterns)
        if is_junk:
            continue
        # Critical anti-placeholder filter (blacklist demo sites + literals)
        if looks_like_placeholder_email(email):
            continue
        if email not in filtered_emails:
            filtered_emails.append(email)

    return filtered_emails


async def extract_emails_from_website(website_url):
    """Extract emails from homepage + contact pages (timeout=3s, placeholder-safe)."""
    emails = set()
    urls_to_check = [website_url]

    for path in CONTACT_PATHS:
        if not website_url.endswith("/"):
            urls_to_check.append(f"{website_url}{path}")
        else:
            urls_to_check.append(f"{website_url}{path[1:]}")

    for url in urls_to_check:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = requests.get(url, headers=headers, timeout=3)
            response.raise_for_status()

            found_emails = extract_and_filter_emails(response.text)
            emails.update(found_emails)

            # Also check mailto links (then filter placeholder mailto:)
            soup = BeautifulSoup(response.text, "lxml")
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if href.startswith("mailto:"):
                    email = href.replace("mailto:", "").strip()
                    if EMAIL_PATTERN.match(email) and not looks_like_placeholder_email(email):
                        emails.add(email)
        except Exception:
            continue

    return list(emails)


def extract_clean_company_context(html_content):
    """Extract readable company context from raw HTML (meta/H1/H2/meaningful p)."""
    if not html_content:
        return ""

    try:
        soup = BeautifulSoup(html_content, "lxml")
    except Exception:
        soup = BeautifulSoup(html_content, "html.parser")

    context_parts = []
    try:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            context_parts.append(meta_desc["content"].strip())
    except Exception:
        pass
    try:
        og_desc = soup.find("meta", attrs={"property": "og:description"})
        if og_desc and og_desc.get("content"):
            context_parts.append(og_desc["content"].strip())
    except Exception:
        pass
    try:
        for h1 in soup.find_all("h1"):
            txt = h1.get_text(strip=True)
            if txt and len(txt) > 3:
                context_parts.append(txt)
    except Exception:
        pass
    try:
        paragraphs = soup.find_all("p")
        meaningful_count = 0
        for p in paragraphs:
            txt = p.get_text(strip=True)
            if txt and len(txt) > 40 and meaningful_count < 3:
                lower_txt = txt.lower()
                if not any(skip in lower_txt for skip in ["cookie", "privacy polic", "terms of use", "copyright", "all rights reserved"]):
                    context_parts.append(txt)
                    meaningful_count += 1
    except Exception:
        pass
    try:
        for h2 in soup.find_all("h2")[:5]:
            txt = h2.get_text(strip=True)
            if txt and len(txt) > 3:
                context_parts.append(f"Section: {txt}")
    except Exception:
        pass

    combined = " ".join(context_parts)
    combined = re.sub(r'\s+', ' ', combined).strip()
    return combined[:2500]


async def fetch_company_context(website_url):
    """Fetch context from homepage + about page variants; return clean summary."""
    all_html = []
    urls_to_check = [website_url]
    for path in ABOUT_PATHS:
        if website_url.endswith("/"):
            urls_to_check.append(f"{website_url}{path[1:]}")
        else:
            urls_to_check.append(f"{website_url}{path}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    for url in urls_to_check:
        try:
            response = requests.get(url, headers=headers, timeout=3)
            if response.status_code == 200:
                all_html.append(response.text)
        except Exception:
            continue

    if not all_html:
        return ""
    return extract_clean_company_context("\n".join(all_html))


async def process_single_listing(listing, source, worksheet):
    """Shared processor: verify → website context → emails → Gemini pitch → send → sheets.

    Uses the new `draft_email()` tuple output so the Status column explicitly reads
    'Sent (Gemini API Maxed - Used Fallback Template)' when Gemini returns 429.
    """
    name = sanitize_for_console(listing["name"])
    website = sanitize_for_console(listing.get("website", "N/A"))
    phone = sanitize_for_console(listing.get("phone", "N/A"))
    source = sanitize_for_console(source or "Unknown")
    primary_email = "N/A"
    company_context = ""

    safe_print(f"\n========================================")
    safe_print(f"--- Processing Lead (Source: {source}) ---")
    safe_print(f"  [VERIFY] Source:         {source}")
    safe_print(f"  [VERIFY] Company Name:   {name}")
    safe_print(f"  [VERIFY] Website URL:    {website}")
    safe_print(f"  [VERIFY] Phone:          {phone}")

    # Seed with Hotfrog directory description if available
    hotfrog_desc = sanitize_for_console(listing.get("description", "") or "").strip()
    if hotfrog_desc and len(hotfrog_desc) > 10:
        company_context = f"Directory listing description: {hotfrog_desc}"
        safe_print(f"  [VERIFY] Source Description ({len(hotfrog_desc)} chars):")
        safe_print(f"    {hotfrog_desc[:400]}{'...' if len(hotfrog_desc) > 400 else ''}")

    if website and website != "N/A":
        # Step 1: Fetch live website context
        try:
            safe_print(f"  [+] Visiting website to extract company context...")
            site_ctx = await fetch_company_context(website)
            if site_ctx:
                if company_context:
                    company_context = company_context + "\n\nWebsite content: " + site_ctx
                else:
                    company_context = site_ctx
                safe_print(f"  [VERIFY] Company Context ({len(company_context)} chars total):")
                preview = sanitize_for_console(company_context[:500]).replace('\n', ' ')
                safe_print(f"    {preview}{'...' if len(company_context) > 500 else ''}")
            elif not company_context:
                safe_print(f"  [-] No company context extracted from website")
        except Exception as e:
            safe_print(f"  [SKIPPED] Error fetching company context: {e}")

        # Step 2: Extract emails (placeholder-safe now)
        try:
            safe_print(f"  [+] Searching for email addresses...")
            emails = await extract_emails_from_website(website)
            if emails:
                primary_email = emails[0]
                safe_print(f"  [VERIFY] Found Email: {primary_email}")
            else:
                safe_print(f"  [-] No email found for {name} on {website}")
        except Exception as e:
            safe_print(f"  [SKIPPED] Error extracting emails: {e}")
            import traceback
            traceback.print_exc()

    pitch = "N/A"
    status = "No Email Found"
    gemini_used_fallback = False
    gemini_reason = None

    if primary_email and primary_email != "N/A" and not looks_like_placeholder_email(primary_email):
        # REQUIRED VERIFICATION PRINT BLOCK BEFORE GENERATING EMAIL
        safe_print(f"\n  ==================================")
        safe_print(f"  [EMAIL GEN] Generating personalized outreach email")
        safe_print(f"    Source:        {source}")
        safe_print(f"    Company:       {name}")
        safe_print(f"    Website:       {website}")
        safe_print(f"    Recipient:     {primary_email}")
        safe_print(f"    Context Len:   {len(company_context)} chars")
        if company_context:
            ctx_preview = sanitize_for_console(company_context[:250]).replace('\n', ' ')
            safe_print(f"    Context Snippet: {ctx_preview}...")
        safe_print(f"  ==================================")

        # Generate pitch via Gemini — uses tuple output so we can tag quota fallback
        lead_info = {
            "name": name,
            "website": website,
            "phone": phone,
            "website_content": company_context
        }
        pitch, gemini_used_fallback, gemini_reason = draft_email(lead_info, is_follow_up=False)

        safe_print(f"\n  [EMAIL PREVIEW] Generated Pitch:")
        pitch_preview = sanitize_for_console((pitch[:600] if pitch else "(empty)"))
        safe_print(f"    {pitch_preview.replace(chr(10), ' | ')}...")

        # Dispatch using the real extracted email variable — NOT hardcoded
        subject = f"Quick question about {name}"
        email_sent = send_email(primary_email, subject, pitch)

        # Build Status — explicitly tag 429 quota fallback per user spec
        if email_sent:
            is_quota_fallback = gemini_used_fallback and (
                (gemini_reason and "429" in str(gemini_reason)) or
                (gemini_reason and "quota" in str(gemini_reason).lower())
            )
            if is_quota_fallback:
                status = "Sent (Gemini API Maxed - Used Fallback Template)"
            elif gemini_used_fallback:
                status = "Sent (Non-AI Fallback Template)"
            else:
                status = "Sent"
        else:
            status = "Failed to Send"
        safe_print(f"  [EMAIL RESULT] Status: {status}")
    elif primary_email and looks_like_placeholder_email(primary_email):
        safe_print(f"  [BLOCKED] Extracted email '{primary_email}' matched placeholder pattern — "
                   f"treating as No Email Found so it won't be sent.")
        primary_email = "N/A"

    # Append to Google Sheets
    if worksheet:
        _ensure_headers(worksheet)
        try:
            initial_email_sent_ts = "" if status.startswith("No Email Found") or status.startswith("Failed") or status.startswith("Outreach") else datetime.now().isoformat()
            emails_str = primary_email if primary_email != "N/A" else "N/A"
            row_data = [
                name,
                phone,
                website,
                emails_str,
                pitch,
                status,
                source,
                initial_email_sent_ts,
                "",
                ""
            ]
            worksheet.append_row(row_data)
            safe_print(f"  [SHEETS SUCCESS] Recorded {name} (Source: {source}) in Google Sheets")
            safe_print(f"  [SHEETS STATUS COLUMN] -> {status}")
        except Exception as e:
            safe_print(f"  [SHEETS ERROR] Failed to record {name}: {e}")
            import traceback
            traceback.print_exc()

    return (name, website, primary_email, status, source)


async def scrape_google_maps(search_query, num_results=20, worksheet=None):
    """Scrape Google Maps for business leads, harvest first, process later."""
    listings_data = []

    async with async_playwright() as p:
        print("Launching browser (Google Maps)...")
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1920,1080"
            ]
        )
        page = await browser.new_page()
        print("Browser launched, navigating to Google Maps...")

        search_url = f"https://www.google.com/maps/search/{search_query.replace(' ', '+')}"
        try:
            await page.goto(search_url, timeout=60000)
        except Exception as e:
            print(f"Navigation timeout or error: {e}, continuing...")
        await page.wait_for_timeout(8000)
        try:
            await page.screenshot(path="google_maps_screenshot.png")
            print("Google Maps screenshot saved to google_maps_screenshot.png")
        except Exception as e:
            print(f"Failed to save screenshot: {e}")

        for _ in range(5):
            await page.mouse.wheel(0, 1000)
            await page.wait_for_timeout(1500)

        listings = []
        for sel in ["div[role='article']", "div.Nv2PK", "div.lI9IFe"]:
            found = await page.query_selector_all(sel)
            if found:
                listings = found
                print(f"Found {len(listings)} listings using selector: {sel}")
                break

        if not listings:
            print("[WARNING] No listings found with any selector!")

        for i, listing in enumerate(listings[:num_results]):
            try:
                print(f"\n--- Harvesting listing {i+1} (Google Maps) ---")

                name = "N/A"
                preclick_name_selectors = [
                    "h3", ".fontHeadlineSmall", ".fontHeadlineMedium", ".fontDisplayMedium",
                    "div[role='heading']", "span[role='heading']",
                    ".qBF1Pd", ".NrDZNb", ".k9grif", "div > a"
                ]
                for sel in preclick_name_selectors:
                    try:
                        el = await listing.query_selector(sel)
                        if el:
                            text = (await el.inner_text()).strip()
                            if text and 2 < len(text) < 150 and text != "N/A":
                                name = text
                                break
                    except Exception:
                        continue
                if name == "N/A":
                    try:
                        a_tag = await listing.query_selector("a")
                        if a_tag:
                            for attr in ["aria-label", "title", "data-label"]:
                                val = await a_tag.get_attribute(attr)
                                if val and 2 < len(val) < 150:
                                    name = val
                                    break
                    except Exception:
                        pass

                try:
                    await listing.click()
                    await page.wait_for_timeout(4000)
                except Exception as click_err:
                    print(f"Could not click listing {i}: {click_err}")
                    if name == "N/A":
                        continue

                if name == "N/A" or len(name) < 3 or name.lower().startswith("http"):
                    detail_name_selectors = [
                        "h1", "h2",
                        ".fontHeadlineLarge", ".fontDisplayLarge", ".fontHeadlineMedium",
                        ".DUwDvf", ".x3AX1", ".k9grif",
                        "div[role='heading']", "span[role='heading']"
                    ]
                    for sel in detail_name_selectors:
                        try:
                            el = await page.query_selector(sel)
                            if el:
                                text = (await el.inner_text()).strip()
                                if (text and 2 < len(text) < 150
                                        and text != "N/A" and not text.lower().startswith("http")
                                        and "cookie" not in text.lower()
                                        and "sign in" not in text.lower()):
                                    name = text
                                    break
                        except Exception:
                            continue

                phone = "N/A"
                phone_selectors = [
                    "button[data-item-id*='phone']",
                    "[data-tooltip*='Phone']",
                    "[data-item-id*='phone']",
                    "div.Io6YTe"
                ]
                for sel in phone_selectors:
                    try:
                        phones = await page.query_selector_all(sel)
                        for p_el in phones:
                            p_text = (await p_el.inner_text()).strip()
                            digits = re.sub(r'\D', '', p_text)
                            if len(digits) >= 7:
                                phone = p_text
                                break
                        if phone != "N/A":
                            break
                    except Exception:
                        continue

                website = "N/A"
                website_selectors = [
                    "a[data-item-id='authority']",
                    "a[data-item-id*='website']",
                    "a[data-tooltip*='Website']",
                    "a[aria-label*='Website']",
                    "a.CsEnq", "a.rogA2c"
                ]
                for sel in website_selectors:
                    try:
                        web_el = await page.query_selector(sel)
                        if web_el:
                            href = await web_el.get_attribute("href")
                            if href and "http" in href:
                                clean_href = href
                                if "/url?q=" in href:
                                    parsed = up.urlparse(href)
                                    qs = up.parse_qs(parsed.query)
                                    if "q" in qs and qs["q"]:
                                        clean_href = qs["q"][0]
                                if not any(g in clean_href for g in ["google.com", "googleusercontent", "ggpht"]):
                                    website = clean_href
                                    break
                    except Exception:
                        continue

                if website == "N/A":
                    try:
                        all_links = await page.query_selector_all("a")
                        for a_el in all_links:
                            href = await a_el.get_attribute("href")
                            if not href or "http" not in href:
                                continue
                            clean_href = href
                            if "/url?q=" in href:
                                parsed = up.urlparse(href)
                                qs = up.parse_qs(parsed.query)
                                if "q" in qs and qs["q"]:
                                    clean_href = qs["q"][0]
                            if (not any(g in clean_href for g in ["google.com", "googleusercontent", "ggpht", "googleapis"])
                                    and "maps." not in clean_href):
                                link_text = (await a_el.inner_text()).strip()
                                if link_text and len(link_text) < 80:
                                    website = clean_href
                                    break
                                elif website == "N/A":
                                    website = clean_href
                    except Exception:
                        pass

                if website == "N/A":
                    try:
                        candidate = await page.evaluate("""() => {
                            const els = document.querySelectorAll('[data-website-url], [data-url], [data-official-url]');
                            for (const e of els) {
                                for (const attr of ['data-website-url', 'data-url', 'data-official-url']) {
                                    const v = e.getAttribute(attr);
                                    if (v && v.startsWith('http') && !v.includes('google')) return v;
                                }
                            }
                            return null;
                        }""")
                        if candidate:
                            website = candidate
                    except Exception:
                        pass

                name = sanitize_for_console(name)
                website = sanitize_for_console(website)
                phone = sanitize_for_console(phone)
                safe_print(f"[VERIFY] Source:             Google Maps")
                safe_print(f"[VERIFY] Scraped Company Name: {name}")
                safe_print(f"[VERIFY] Scraped Website:      {website}")
                safe_print(f"[VERIFY] Scraped Phone:        {phone}")

                listings_data.append({
                    "name": name,
                    "phone": phone,
                    "website": website
                })
                safe_print(f"Harvested listing {i+1} (Google Maps): {name}")

            except Exception as e:
                print(f"Error harvesting listing {i}: {e}")
                import traceback
                traceback.print_exc()
                continue

        await browser.close()
        print(f"\nHarvested {len(listings_data)} listings from Google Maps, closing Playwright...")

    safe_print(f"\n=== Processing {len(listings_data)} Google Maps leads ===")
    for listing in listings_data:
        await process_single_listing(listing, source="Google Maps", worksheet=worksheet)


def _hotfrog_base_domains(location_str, query_str=""):
    """Return a prioritized list of Hotfrog base URLs (+ path prefixes) to try.

    For each region we try:
      1. The country-specific ccTLD (e.g. hotfrog.pk)
      2. hotfrog.com/<cc>/ path prefix   (e.g. /pk/ — user requested fallback)
      3. hotfrog.com business search page (international default)
    If a DNS-level failure happens, scrape_hotfrog will automatically try the
    next URL in the returned list.
    """
    joined = f"{location_str or ''} {query_str or ''}".lower()

    # Pakistan + common Pakistan cities
    pk_keywords = [
        "pakistan", "karachi", "lahore", "islamabad", "rawalpindi",
        "peshawar", "quetta", "faisalabad", "multan", "hyderabad", "sialkot",
        "gujranwala", "abottabad", "sargodha", "bahawalpur", "pk"
    ]
    if any(k in joined for k in pk_keywords):
        return [
            "https://www.hotfrog.pk",
            "https://www.hotfrog.com/pk",
            "https://www.hotfrog.co/pk",
            "https://pk.hotfrog.com",
            "https://www.hotfrog.com",
        ]

    # UK
    uk_keywords = ["uk", "united kingdom", "london", "manchester", "birmingham", "leeds", "glasgow"]
    if any(k in joined for k in uk_keywords):
        return [
            "https://www.hotfrog.co.uk",
            "https://www.hotfrog.com/uk",
            "https://www.hotfrog.com",
        ]

    # Australia
    au_keywords = ["australia", "sydney", "melbourne", "brisbane", "perth", "adelaide"]
    if any(k in joined for k in au_keywords):
        return [
            "https://www.hotfrog.com.au",
            "https://www.hotfrog.com/au",
            "https://www.hotfrog.com",
        ]

    # India
    in_keywords = ["india", "mumbai", "delhi", "bengaluru", "bangalore", "chennai", "hyderabad", "kolkata", "pune"]
    if any(k in joined for k in in_keywords):
        return [
            "https://www.hotfrog.in",
            "https://www.hotfrog.com/in",
            "https://www.hotfrog.com",
        ]

    # UAE
    uae_keywords = ["uae", "dubai", "abu dhabi", "sharjah", "united arab emirates"]
    if any(k in joined for k in uae_keywords):
        return [
            "https://www.hotfrog.ae",
            "https://www.hotfrog.com/ae",
            "https://www.hotfrog.com",
        ]

    # Default: .com (international)
    return ["https://www.hotfrog.com"]


# Backwards-compat single-domain helper (used by direct URL fallback formatting)
def _hotfrog_base_domain(location_str, query_str=""):
    return _hotfrog_base_domains(location_str, query_str)[0]


async def scrape_hotfrog(search_query, num_results=20, worksheet=None):
    """Hotfrog scraper — uses country-specific base domain (e.g., hotfrog.pk for Pakistan).

    Anti-bot: Random 4-9 second human_delay() between every navigation/search/click/listing.
    Extracts: Name, Website, short directory description -> fed to Gemini via shared processor.
    Source column written as "Hotfrog" in sheets.
    """
    listings_data = []

    # Parse query into industry + location when "in" separator present
    industry_keywords = search_query
    location = ""
    if " in " in search_query.lower():
        left, right = search_query.lower().rsplit(" in ", 1)
        industry_keywords = left.strip()
        location = right.strip()

    # PICK REGION-SPECIFIC HOTFROG DOMAIN (critical for Karachi / Pakistan)
    base_domain_candidates = _hotfrog_base_domains(location, search_query)
    safe_print(f"\n[Hotfrog] Candidate base URLs (tried in order until reachable): {base_domain_candidates}")
    safe_print(f"[Hotfrog] Industry keywords: {industry_keywords}")
    if location:
        safe_print(f"[Hotfrog] Location:          {location}")

    async with async_playwright() as p:
        safe_print("[Hotfrog] Launching browser...")
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1920,1080"
            ]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="en-US"
        )
        page = await context.new_page()

        async def human_delay(_min=4, _max=9):
            delay = random.uniform(float(_min), float(_max))
            await asyncio.sleep(delay)

        # ---- Step 1: Find a REACHABLE Hotfrog base URL across candidates ----
        BASE_DOMAIN = None
        for candidate in base_domain_candidates:
            start_url = candidate.rstrip("/") + "/"
            try:
                safe_print(f"[Hotfrog] Trying base URL: {start_url} ...")
                resp = await page.goto(start_url, timeout=45000, wait_until="domcontentloaded")
                if resp is None:
                    safe_print(f"[Hotfrog]   → got null response, trying next candidate")
                    continue
                status = resp.status
                # 4xx/5xx fatal for root; treat as unreachable candidate
                if status >= 400:
                    safe_print(f"[Hotfrog]   → HTTP {status}, trying next candidate")
                    continue
                BASE_DOMAIN = candidate.rstrip("/")
                safe_print(f"[Hotfrog]   → reachable! Using {BASE_DOMAIN}/ for the rest of this run.")
                break
            except Exception as e:
                err_msg = str(e)
                safe_print(f"[Hotfrog]   → unreachable ({type(e).__name__}): {err_msg[:160]} — moving to next candidate")
                continue

        if BASE_DOMAIN is None:
            safe_print("[WARNING] [Hotfrog] ALL candidate base URLs failed on this network. Hotfrog phase skipped (0 listings) — Google Maps results still complete OK.")
            await browser.close()
            return []

        await human_delay(4, 9)

        # ---- Step 2: Fill search form + submit + delay ----
        submitted = False
        try:
            what_selectors = [
                "input#what",
                "input[name='what']",
                "input[placeholder*='what' i]",
                "input[placeholder*='business' i]",
                "input[placeholder*='keyword' i]"
            ]
            for sel in what_selectors:
                what = await page.query_selector(sel)
                if what:
                    safe_print(f"[Hotfrog] Filling 'what' field using {sel}")
                    await what.click()
                    await human_delay(1.0, 2.5)
                    await what.fill(industry_keywords)
                    submitted = True
                    break

            if location:
                where_selectors = [
                    "input#where",
                    "input[name='where']",
                    "input[placeholder*='where' i]",
                    "input[placeholder*='city' i]",
                    "input[placeholder*='location' i]",
                    "input[placeholder*='zip' i]",
                    "input[placeholder*='town' i]"
                ]
                for sel in where_selectors:
                    where = await page.query_selector(sel)
                    if where:
                        safe_print(f"[Hotfrog] Filling 'where' field using {sel}")
                        await where.click()
                        await human_delay(1.0, 2.5)
                        await where.fill(location)
                        break

            if submitted:
                await human_delay(2, 4)
                submitted = False
                for btn_selector in [
                    "button[type='submit']",
                    "input[type='submit']",
                    "button:has-text('Search')",
                    "input#search",
                    ".search-btn",
                    "[data-action='search']",
                    "[id*='search'][type='submit']"
                ]:
                    btn = await page.query_selector(btn_selector)
                    if btn:
                        safe_print(f"[Hotfrog] Clicking search button: {btn_selector}")
                        await btn.click()
                        submitted = True
                        break
                if not submitted:
                    safe_print("[Hotfrog] Submitting search via Enter key")
                    await page.keyboard.press("Enter")
                    submitted = True
                await human_delay(5, 9)
        except Exception as e:
            safe_print(f"[Hotfrog] Form-fill issue: {e} — using direct URL fallback")

        # ---- Step 3: Direct URL fallback + delay ----
        if not submitted:
            try:
                if location:
                    direct_url = (
                        f"{BASE_DOMAIN.rstrip('/')}/search/"
                        f"{up.quote_plus(location)}/{up.quote_plus(industry_keywords)}"
                    )
                else:
                    direct_url = (
                        f"{BASE_DOMAIN.rstrip('/')}/search?keyword={up.quote_plus(industry_keywords)}"
                    )
                safe_print(f"[Hotfrog] Using direct URL: {direct_url}")
                await page.goto(direct_url, timeout=90000, wait_until="domcontentloaded")
                await human_delay(5, 9)
            except Exception as e:
                safe_print(f"[Hotfrog] Direct URL navigation failed: {e}")

        try:
            await page.screenshot(path="hotfrog_screenshot.png")
            safe_print("[Hotfrog] Screenshot saved to hotfrog_screenshot.png")
        except Exception:
            pass

        # ---- Step 4: Extract listings from results page ----
        safe_print("[Hotfrog] Extracting listings from results page...")
        listing_selectors = [
            "article.business",
            ".business-listing",
            ".listing",
            ".result-item",
            "div[data-business-id]",
            "li.business-item",
            ".search-result",
            ".card-business",
            ".company-card",
            ".business-card"
        ]
        found_listings = []
        for sel in listing_selectors:
            els = await page.query_selector_all(sel)
            if els:
                found_listings = els
                safe_print(f"[Hotfrog] Found {len(els)} listings using selector: {sel}")
                break

        if not found_listings:
            generic = await page.query_selector_all("a[href*='/company/'], a[href*='/business/'], a[href*='/companies/']")
            if generic:
                seen_parents = set()
                for a in generic:
                    par = await a.evaluate_handle("el => el.closest('div, li, article, section')")
                    p_hex = str(par)
                    if p_hex not in seen_parents:
                        seen_parents.add(p_hex)
                        found_listings.append(a)
                safe_print(f"[Hotfrog] Fallback: found {len(found_listings)} company-link containers")

        if not found_listings:
            safe_print("[WARNING] [Hotfrog] No listings found on page!")

        for i, card in enumerate(found_listings[:num_results]):
            try:
                safe_print(f"\n--- Harvesting Hotfrog listing {i+1} ---")

                # Name
                name = "N/A"
                name_sels = [
                    "h2", "h3", "h4",
                    ".business-name", ".company-name", ".listing-title",
                    "a[title]", "a[aria-label]", "span[itemprop='name']",
                    "[itemprop='name']", ".result-title", ".company-name__title"
                ]
                for sel in name_sels:
                    try:
                        el = await card.query_selector(sel)
                        if not el:
                            continue
                        text = (await el.inner_text()).strip()
                        if text and 2 < len(text) < 200:
                            name = text
                            break
                    except Exception:
                        continue
                if name == "N/A":
                    try:
                        first_a = await card.query_selector("a")
                        if first_a:
                            for attr in ["title", "aria-label", "data-name"]:
                                v = await first_a.get_attribute(attr)
                                if v and 2 < len(v) < 200:
                                    name = v
                                    break
                            if name == "N/A":
                                t = (await first_a.inner_text()).strip()
                                if t and 2 < len(t) < 200:
                                    name = t
                    except Exception:
                        pass

                # Website — exclude social/hotfrog/google internal links
                website = "N/A"
                web_sels = [
                    "a.website",
                    "a.visit-website",
                    "a[rel*='noopener']",
                    "a[target='_blank']",
                    ".business-url a",
                    ".website-url a",
                    "a[itemprop='url']",
                    "a"
                ]
                for sel in web_sels:
                    try:
                        anchors = await card.query_selector_all(sel)
                        for a in anchors:
                            href = await a.get_attribute("href")
                            if not href or "http" not in href:
                                continue
                            if any(s in href for s in [
                                "hotfrog", "google.", "facebook.", "instagram.",
                                "twitter.", "linkedin.", "youtube.", "yahoo.", "bing."
                            ]):
                                continue
                            website = href
                            break
                        if website != "N/A":
                            break
                    except Exception:
                        continue

                # Description
                description = ""
                desc_sels = [
                    "p.description",
                    ".business-description",
                    ".about",
                    ".listing-description",
                    "span[itemprop='description']",
                    "[itemprop='description']",
                    ".snippet",
                    ".business-snippet",
                    "p"
                ]
                for sel in desc_sels:
                    try:
                        el = await card.query_selector(sel)
                        if not el:
                            continue
                        text = (await el.inner_text()).strip()
                        if text and len(text) > 15:
                            description = text
                            break
                    except Exception:
                        continue
                if not description:
                    try:
                        paras = await card.query_selector_all("p, span")
                        for p in paras:
                            t = (await p.inner_text()).strip()
                            if 25 < len(t) < 1000:
                                description = t
                                break
                    except Exception:
                        pass

                # Phone
                phone = "N/A"
                phone_sels = [
                    ".phone", ".telephone", ".business-phone",
                    "span[itemprop='telephone']",
                    "[itemprop='telephone']",
                    "a[href^='tel:']"
                ]
                for sel in phone_sels:
                    try:
                        el = await card.query_selector(sel)
                        if not el:
                            continue
                        p_text = (await el.inner_text()).strip()
                        digits = re.sub(r'\D', '', p_text)
                        if len(digits) >= 7:
                            phone = p_text
                            break
                        href = await el.get_attribute("href")
                        if href and href.startswith("tel:"):
                            phone = href.replace("tel:", "").strip()
                            break
                    except Exception:
                        continue

                # Sanitize + VERIFY prints BEFORE email generation (spec requirement)
                name = sanitize_for_console(name)
                website = sanitize_for_console(website)
                phone = sanitize_for_console(phone)
                description = sanitize_for_console(description)

                safe_print(f"[VERIFY] Source:             Hotfrog")
                safe_print(f"[VERIFY] Scraped Company Name: {name}")
                safe_print(f"[VERIFY] Scraped Website:      {website}")
                if phone and phone != "N/A":
                    safe_print(f"[VERIFY] Scraped Phone:        {phone}")
                if description:
                    safe_print(f"[VERIFY] Description ({len(description)} chars):  {description[:350]}{'...' if len(description) > 350 else ''}")

                listings_data.append({
                    "name": name,
                    "website": website,
                    "phone": phone,
                    "description": description  # routed to Gemini via shared processor
                })
                safe_print(f"Harvested listing {i+1} (Hotfrog): {name}")

                if i != len(found_listings[:num_results]) - 1:
                    await human_delay(4, 9)

            except Exception as e:
                safe_print(f"[Hotfrog] Error harvesting listing {i}: {e}")
                import traceback
                traceback.print_exc()
                continue

        await browser.close()
        safe_print(f"\nHarvested {len(listings_data)} listings from Hotfrog, closing Playwright...")

    safe_print(f"\n=== Processing {len(listings_data)} Hotfrog leads ===")
    for listing in listings_data:
        await process_single_listing(listing, source="Hotfrog", worksheet=worksheet)

    return listings_data


async def main():
    search_query = input("Enter search keyword: ").strip()
    num_results = int(input("Enter number of results per source (default 20): ") or "20")

    print(f"Starting scrape for: {search_query}")

    worksheet = None
    if SERVICE_ACCOUNT_KEY and os.path.exists(SERVICE_ACCOUNT_KEY):
        worksheet = connect_to_google_sheets()

    await scrape_google_maps(search_query, num_results, worksheet)
    await scrape_hotfrog(search_query, num_results, worksheet)

    print("Scraping complete!")


if __name__ == "__main__":
    asyncio.run(main())
