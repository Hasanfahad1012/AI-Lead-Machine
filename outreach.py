
import os
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
try:
    if GEMINI_API_KEY and GEMINI_API_KEY.strip():
        genai.configure(api_key=GEMINI_API_KEY)
    else:
        print("[SKIPPED] Missing or invalid GEMINI_API_KEY in .env")
except Exception as e:
    print(f"[SKIPPED] Error configuring Gemini: {e}")

# SMTP configuration
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME")
CAL_LINK = os.getenv("CAL_LINK")

# Hardcoded demo/placeholder patterns — NEVER email these.
# These are strings that demo/template sites often leave in their HTML.
# Matched case-insensitively against the whole email address.
PLACEHOLDER_EMAIL_PATTERNS = re.compile(
    r"^(your|you|test|admin|info|contact|example|demo|sample|name|email|user|username|"
    r"support|hello|mail|no-reply|noreply|webmaster|postmaster|foo|bar|baz|someone|nobody|"
    r"placeholder|temp|tmp|dummy|fake|junk|spam|catch.all)?[._-]?[0-9]*"
    r"@(example\.com|example\.org|example\.net|yourdomain\.com|domain\.com|email\.com|"
    r"mailinator\.com|test\.com|demo\.com|company\.com|yoursite\.com|website\.com|"
    r"mydomain\.com|hotmail\.com\.br|gmail\.co\.uk|foo\.com|bar\.com|your-email\.com|"
    r"youremail\.com|e-mail\.com|email-address\.com|providertld\.com|domain)$",
    re.IGNORECASE,
)


def looks_like_placeholder_email(email):
    """Return True if email matches known demo/template/placeholder patterns."""
    if not email:
        return True
    em = email.strip().lower()
    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", em):
        return True
    # Literal exact demo strings often found in templates
    literal_bad = {
        "your@email.com", "you@gmail.com", "your.email@example.com",
        "name@email.com", "email@email.com", "email@example.com",
        "you@youremail.com", "test@example.com", "admin@example.com",
        "contact@example.com", "info@example.com", "support@example.com",
        "hello@example.com", "no-reply@example.com", "noreply@example.com",
        "webmaster@example.com", "postmaster@example.com", "foo@bar.com",
        "foo@baz.com", "bar@foo.com", "example@example.com", "mail@example.com",
        "user@example.com", "username@example.com", "name@company.com",
        "name@yourdomain.com", "you@yourdomain.com", "info@company.com",
        "contact@company.com", "you@company.com", "yourname@yourcompany.com",
        "john@example.com", "jane@example.com", "john.doe@example.com",
        "sales@example.com", "marketing@example.com", "business@example.com",
        "me@example.com", "personal@example.com", "private@example.com",
    }
    if em in literal_bad:
        return True
    # Regex pattern match (covers combinations like info2@example.com etc.)
    if PLACEHOLDER_EMAIL_PATTERNS.match(em):
        return True
    return False


def _fallback_pitch(company_name, website, website_content, has_real_name, has_real_context, is_follow_up):
    """Basic predefined string template used when Gemini is unavailable or rate-limited.

    Never returns a generic "Dear business" letter — always injects the real
    company name and 1-2 business details if available.
    """
    greeting = f"Hi {company_name.split()[0].capitalize()} team," if has_real_name else "Hi there,"
    biz_name_sentence = company_name if has_real_name else "your business"

    # Pull a short ~80 char specific snippet to reference if we have context
    angle = ""
    if has_real_context:
        snippet = website_content[:80].replace("  ", " ").strip()
        if snippet:
            angle = (
                f"After looking into {biz_name_sentence}, I noted your focus on "
                f"\"{snippet}\" — which caught my attention. "
            )

    if is_follow_up:
        return (
            f"{greeting}\n\n"
            f"Hope you had a chance to review my earlier note about how we help "
            f"businesses like {biz_name_sentence} drive more revenue and streamline operations.\n"
            f"{angle}"
            f"Just wanted to circle back — I'd love a quick 15 minutes to walk through a couple of ideas "
            f"specifically for {biz_name_sentence}.\n\n"
            f"If you're open to it, grab a slot that works here: {CAL_LINK}\n\n"
            f"Best,\n{SMTP_FROM_NAME}"
        )

    return (
        f"{greeting}\n\n"
        f"{angle}"
        f"I'm reaching out because we've helped similar local businesses cut overhead and boost productivity "
        f"without adding extra work for their team.\n"
        f"For {biz_name_sentence}, I'd love to show you 2-3 small operational tweaks that typically "
        f"pay for themselves within 60 days.\n\n"
        f"Would you be open to a quick 15-minute call this week? Book here: {CAL_LINK}\n\n"
        f"Best,\n{SMTP_FROM_NAME}"
    )


def draft_email(lead_info, is_follow_up=False):
    """Use Gemini to draft a HIGHLY PERSONALIZED B2B email. NO generic templates allowed.

    Returns a tuple: (email_body, used_fallback_flag, fallback_reason_or_None).
    - used_fallback_flag = True means Gemini was NOT used (caller should mark sheets Status
      with the Gemini API Maxed note).
    - If used_fallback_flag is True, fallback_reason is a short string like "429 quota"
      or "missing key", else None.
    """
    company_name = lead_info.get("name", "N/A").strip() or "N/A"
    website = lead_info.get("website", "N/A").strip() or "N/A"
    phone = lead_info.get("phone", "N/A").strip() or "N/A"
    website_content = (lead_info.get("website_content", "") or "").strip()

    has_real_name = bool(company_name) and company_name != "N/A" and len(company_name) > 2
    has_real_context = bool(website_content) and len(website_content) > 50

    # Fast-path: no Gemini key available
    if not GEMINI_API_KEY or not GEMINI_API_KEY.strip():
        print("[SKIPPED] Gemini API key not available, using predefined fallback template")
        return (
            _fallback_pitch(company_name, website, website_content, has_real_name, has_real_context, is_follow_up),
            True,
            "Missing GEMINI_API_KEY",
        )

    # ==== STRONG, HIGHLY-SPECIFIC PROMPT — FORBIDS GENERIC LANGUAGE ====
    prompt = f"""
You are an elite B2B cold-outreach copywriter. Your job is to write a SHORT (90-140 word) email that feels like it was written one-by-one by a real human who actually researched the company.

--- INPUT DATA ---
Company Name: {company_name}
Website URL: {website}
Phone: {phone}

Website Research (what we learned by visiting their homepage + About page + directory description — THIS IS YOUR MOST IMPORTANT INPUT):
\"\"\"{website_content if website_content else '(no website content available)'}\"\"\"

Email Type: {'FOLLOW-UP EMAIL (they received our first email and did not reply yet. Be polite but persistent, not pushy. Mention that we hope they had a chance to review the earlier note.)' if is_follow_up else 'FIRST OUTREACH EMAIL (cold, respectful, not overly salesy)'}

--- NON-NEGOTIABLE RULES (VIOLATE THESE AND YOU FAIL) ---

1.  PERSONALIZED OPENING LINE — MANDATORY. The very first sentence (after greeting) MUST reference something specific from the Website Research above. It must read like you actually looked at their site.
    - GOOD: "I landed on {company_name if has_real_name else 'your site'} this morning and loved reading about how you specialize in [specific service pulled from website content]."
    - GOOD: "I was on {company_name if has_real_name else 'your website'} just now and noticed your focus on [specific offering/service/value prop from research] — super impressive."
    - BAD:  "I hope this email finds you well." (generic, never use this)
    - BAD:  "I searched your company." (vague, useless)
    - BAD:  "I came across {company_name if has_real_name else 'your business'} and wanted to reach out." (generic, no website reference)

2.  USE THE REAL COMPANY NAME. Never write "your company" when a real name ({company_name}) is available. Use "{company_name}" at least twice.

3.  NAME THEIR ACTUAL WORK. In the pitch body, specifically name 1-2 real things they do that are found in the Website Research. Do NOT make up services. Only use what's in the research. If research is empty, say "from what I can see on your site" but still make it sound specific to {company_name}.

4.  MAKE IT ABOUT THEM FIRST, then pivot to a brief value prop. Do NOT lead with who you are or what you sell. Start with something you genuinely find interesting about THEIR business based on the Website Research.

5.  Tone: Respectful, confident, conversational. No corporate jargon. No "synergize" or "leverage" language.

6.  Keep the ENTIRE email between 90 and 140 words. Short = opened and read.

7.  CTA — one single clear call-to-action at the end. Ask for a brief intro call. Use this EXACT link: {CAL_LINK}

8.  SIGN-OFF — end ONLY with: Best, [newline] {SMTP_FROM_NAME}

9.  DO NOT USE placeholders like "[Company Name]" or N/A. If data says N/A, work around it gracefully. Do not output the literal text "N/A" anywhere in the email.

--- REMINDER FOR FOLLOW-UPS (only applies if this is a follow-up): ---
- Briefly acknowledge you emailed previously
- Do not say "just checking in" — instead, share one new tiny personalized detail or a different angle from the website research
- Keep it even shorter (80-110 words)

Now write the email. Do NOT include a subject line. Do NOT add any commentary or explanation. Output ONLY the plain email body.
"""

    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        generated = response.text.strip()
        # Clean: ensure we don't literally print "N/A" in the email
        if has_real_name:
            generated = generated.replace("N/A", company_name)
        else:
            generated = generated.replace("N/A", "your business")
        return (generated, False, None)
    except Exception as e:
        err_str = str(e)
        is_429 = "429" in err_str or "quota" in err_str.lower() or "rate limit" in err_str.lower()
        reason = "429 quota exceeded" if is_429 else f"{type(e).__name__}"
        safe_msg = err_str[:180] if len(err_str) > 180 else err_str
        if is_429:
            print("[FALLBACK] Gemini 429 quota exceeded. Using predefined fallback template.")
        else:
            print(f"[SKIPPED] Error drafting email with Gemini ({reason}): {safe_msg} → using fallback template.")
        return (
            _fallback_pitch(company_name, website, website_content, has_real_name, has_real_context, is_follow_up),
            True,
            reason,
        )


def send_email(to_email, subject, body):
    """Send email via SMTP to the real extracted target email.

    Uses the dynamic `to_email` parameter for both msg['To'] header and actual
    smtplib.sendmail() recipients list — no hardcoded addresses.
    """
    if not to_email or not isinstance(to_email, str):
        print("send_email() called with empty / invalid to_email — ABORTING send.")
        return False
    to_email = to_email.strip()
    if looks_like_placeholder_email(to_email):
        print(f"BLOCKED: refusing to send to placeholder/demo address '{to_email}'.")
        return False

    msg = MIMEMultipart()
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
    msg["To"] = to_email  # DYNAMIC: always uses the scraped target email variable
    msg["Subject"] = subject
    msg["Reply-To"] = SMTP_USER

    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASSWORD)
            # Send for real: recipients = [to_email] (NOT hardcoded!)
            server.sendmail(SMTP_USER, [to_email], msg.as_string())
        print(f"[SMTP OK] Email sent successfully to {to_email}")
        return True
    except Exception as e:
        print(f"[SMTP FAIL] Failed to send email to {to_email}: {e}")
        return False


def send_initial_outreach(lead):
    """Send initial outreach email to lead — uses the actual scraped lead.emails[0]."""
    if not lead.get("emails"):
        print("No email address found for this lead")
        return False
    # Select the real extracted email dynamically
    target_email = lead["emails"][0] if isinstance(lead["emails"], list) else lead["emails"]
    if not target_email or looks_like_placeholder_email(target_email):
        print(f"send_initial_outreach: placeholder or missing email '{target_email}' — skipping send.")
        return False

    lead_for_draft = {
        "name": lead.get("name", "N/A"),
        "website": lead.get("website", "N/A"),
        "phone": lead.get("phone", "N/A"),
        "website_content": lead.get("website_content", "") or ""
    }

    subject = f"Quick question about {lead_for_draft['name'] if lead_for_draft['name'] != 'N/A' else 'your business'}"
    # draft_email returns (body, used_fallback_flag, reason) — but this legacy helper discards flag
    body, _used_fallback, _reason = draft_email(lead_for_draft, is_follow_up=False)
    return send_email(target_email, subject, body)


def send_follow_up(lead):
    """Send follow-up email to lead — uses the actual scraped lead.emails[0]."""
    if not lead.get("emails"):
        print("No email address found for this lead")
        return False
    target_email = lead["emails"][0] if isinstance(lead["emails"], list) else lead["emails"]
    if not target_email or looks_like_placeholder_email(target_email):
        print(f"send_follow_up: placeholder or missing email '{target_email}' — skipping send.")
        return False

    lead_for_draft = {
        "name": lead.get("name", "N/A"),
        "website": lead.get("website", "N/A"),
        "phone": lead.get("phone", "N/A"),
        "website_content": lead.get("website_content", "") or ""
    }

    subject = f"Following up: Re: {lead_for_draft['name'] if lead_for_draft['name'] != 'N/A' else 'your business'}"
    body, _used_fallback, _reason = draft_email(lead_for_draft, is_follow_up=True)
    return send_email(target_email, subject, body)
