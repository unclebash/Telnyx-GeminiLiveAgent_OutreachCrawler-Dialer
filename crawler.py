import re
import urllib.parse
from playwright.sync_api import sync_playwright

EMAIL_REGEX = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'

# Exclude common image/static extensions to avoid false email matches (e.g. logo@2x.png)
EXCLUDED_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.pdf', '.css', '.js')

def clean_emails(emails):
    cleaned = set()
    for email in emails:
        # Lowercase and clean
        email_clean = email.strip().lower()
        # Verify it doesn't end with an excluded extension
        if not any(email_clean.endswith(ext) for ext in EXCLUDED_EXTENSIONS):
            cleaned.add(email_clean)
    return list(cleaned)

def crawl_website_for_email(url: str) -> str | None:
    """
    Crawls the website at URL to extract a contact email.
    First checks the homepage, and if no email is found, attempts to visit a contact/about page.
    """
    if not url:
        return None
        
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            emails_found = []
            
            # 1. Try visiting homepage
            try:
                page.goto(url, timeout=10000, wait_until="domcontentloaded")
                content = page.content()
                emails_found.extend(re.findall(EMAIL_REGEX, content))
            except Exception as e:
                print(f"Error loading homepage {url}: {e}")
                browser.close()
                return None
                
            # Clean emails found on homepage
            cleaned = clean_emails(emails_found)
            if cleaned:
                # Prioritize emails starting with contact/info/hello
                for email in cleaned:
                    if any(email.startswith(prefix) for prefix in ['info', 'contact', 'hello', 'support', 'office', 'admin']):
                        browser.close()
                        return email
                browser.close()
                return cleaned[0]
                
            # 2. Look for contact/about links
            try:
                links = page.locator('a').all()
                contact_link = None
                for link in links:
                    href = link.get_attribute('href')
                    text = link.inner_text().lower()
                    if href:
                        href_lower = href.lower()
                        if 'contact' in href_lower or 'about' in href_lower or 'contact' in text or 'about' in text:
                            # Resolve relative URL
                            contact_link = urllib.parse.urljoin(url, href)
                            break
                            
                if contact_link:
                    page.goto(contact_link, timeout=8000, wait_until="domcontentloaded")
                    content = page.content()
                    emails_found.extend(re.findall(EMAIL_REGEX, content))
            except Exception as e:
                print(f"Error checking subpage for {url}: {e}")
                
            browser.close()
            
            cleaned = clean_emails(emails_found)
            if cleaned:
                for email in cleaned:
                    if any(email.startswith(prefix) for prefix in ['info', 'contact', 'hello', 'support', 'office', 'admin']):
                        return email
                return cleaned[0]
                
    except Exception as e:
        print(f"Playwright execution error for {url}: {e}")
        
    return None
