import os
import base64
import json
from email.mime.text import MIMEText
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/gmail.readonly'
]

class StandaloneGmailClient:
    def __init__(self, base_dir: str):
        self.creds_path = os.path.join(base_dir, "gmail_credentials.json")
        # Fallback to parent config folder if local file doesn't exist
        self.fallback_creds_path = os.path.join(os.path.dirname(base_dir), "config", "gmail_credentials.json")
        self.token_path = os.path.join(base_dir, "gmail_token.json")
        self.service = None

    def is_configured(self) -> bool:
        """Returns True if the credentials file exists."""
        if os.path.exists(self.creds_path):
            return True
        if os.path.exists(self.fallback_creds_path):
            self.creds_path = self.fallback_creds_path
            return True
        return False

    def is_authenticated(self) -> bool:
        """Returns True if a valid token is present."""
        if not os.path.exists(self.token_path):
            return False
        try:
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
            if creds and creds.valid:
                return True
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(self.token_path, 'w') as token:
                    token.write(creds.to_json())
                return True
        except Exception:
            pass
        return False

    def authenticate_interactive(self) -> bool:
        """Runs the interactive OAuth flow to create/refresh the token."""
        if not os.path.exists(self.creds_path):
            return False
        
        try:
            flow = InstalledAppFlow.from_client_secrets_file(self.creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
            with open(self.token_path, 'w') as token:
                token.write(creds.to_json())
            self.service = build('gmail', 'v1', credentials=creds)
            return True
        except Exception as e:
            print(f"OAuth Flow Error: {e}")
            return False

    def get_service(self):
        """Loads and returns Gmail API service client."""
        if self.service:
            return self.service
            
        creds = None
        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
            except Exception:
                pass

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(self.token_path, 'w') as token:
                    token.write(creds.to_json())
            except Exception:
                creds = None

        if not creds or not creds.valid:
            return None

        try:
            self.service = build('gmail', 'v1', credentials=creds)
            return self.service
        except Exception:
            return None

    def send_email(self, to_email: str, subject: str, body: str, is_html: bool = False) -> bool:
        """Sends an email directly."""
        service = self.get_service()
        if not service:
            return False

        try:
            message = MIMEText(body, 'html' if is_html else 'plain')
            message['to'] = to_email
            message['subject'] = subject
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            
            send_body = {'raw': raw_message}
            service.users().messages().send(userId='me', body=send_body).execute()
            return True
        except Exception as e:
            print(f"Failed to send email to {to_email}: {e}")
            return False

    def create_draft(self, to_email: str, subject: str, body: str, is_html: bool = False) -> bool:
        """Creates an email draft instead of sending immediately."""
        service = self.get_service()
        if not service:
            return False

        try:
            message = MIMEText(body, 'html' if is_html else 'plain')
            message['to'] = to_email
            message['subject'] = subject
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            
            draft_body = {
                'message': {
                    'raw': raw_message
                }
            }
            service.users().drafts().create(userId='me', body=draft_body).execute()
            return True
        except Exception as e:
            print(f"Failed to create draft to {to_email}: {e}")
            return False
            
    def get_sender_email(self) -> str:
        """Gets email address of the authenticated Gmail user."""
        service = self.get_service()
        if not service:
            return "Not Connected"
        try:
            profile = service.users().getProfile(userId='me').execute()
            return profile.get("emailAddress", "Connected")
        except Exception:
            return "Connected"
