import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets'
]

class StandaloneSheetsClient:
    def __init__(self, base_dir: str):
        self.creds_path = os.path.join(base_dir, "gmail_credentials.json")
        self.fallback_creds_path = os.path.join(os.path.dirname(base_dir), "config", "gmail_credentials.json")
        self.token_path = os.path.join(base_dir, "sheets_token.json")
        self.service = None

    def is_configured(self) -> bool:
        if os.path.exists(self.creds_path):
            return True
        if os.path.exists(self.fallback_creds_path):
            self.creds_path = self.fallback_creds_path
            return True
        return False

    def is_authenticated(self) -> bool:
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
        if not os.path.exists(self.creds_path):
            return False
        try:
            flow = InstalledAppFlow.from_client_secrets_file(self.creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
            with open(self.token_path, 'w') as token:
                token.write(creds.to_json())
            self.service = build('sheets', 'v4', credentials=creds)
            return True
        except Exception as e:
            print(f"Sheets OAuth Flow Error: {e}")
            return False

    def get_service(self):
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
            self.service = build('sheets', 'v4', credentials=creds)
            return self.service
        except Exception:
            return None

    def create_headers_if_empty(self, spreadsheet_id: str) -> bool:
        """Initializes column headers if sheet is empty, and applies Status dropdown validation."""
        service = self.get_service()
        if not service:
            return False
        try:
            range_name = 'Sheet1!A1:I1'
            result = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=range_name
            ).execute()
            rows = result.get('values', [])
            if not rows:
                headers = [["Company Name", "Phone", "Location", "Status", "Donation Amount", "Notes", "Website", "Email", "Place ID"]]
                body = {'values': headers}
                service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id, range=range_name,
                    valueInputOption='USER_ENTERED', body=body
                ).execute()
            self.apply_status_dropdown(spreadsheet_id)
            return True
        except Exception as e:
            print(f"Error initializing headers: {e}")
            return False

    def apply_status_dropdown(self, spreadsheet_id: str) -> bool:
        """Applies a Status dropdown validation (Pending, Called, Donated, Denied) to Column E."""
        service = self.get_service()
        if not service:
            return False
        try:
            spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            sheets = spreadsheet.get('sheets', [])
            grid_sheet_id = 0
            if sheets:
                grid_sheet_id = sheets[0]['properties']['sheetId']
                
            body = {
                "requests": [
                    {
                        "setDataValidation": {
                            "range": {
                                "sheetId": grid_sheet_id,
                                "startRowIndex": 1,
                                "startColumnIndex": 3,
                                "endColumnIndex": 4
                            },
                            "rule": {
                                "condition": {
                                    "type": "ONE_OF_LIST",
                                    "values": [
                                        {"userEnteredValue": "Pending"},
                                        {"userEnteredValue": "Called"},
                                        {"userEnteredValue": "Donated"},
                                        {"userEnteredValue": "Denied"}
                                    ]
                                },
                                "showCustomUi": True,
                                "strict": True
                            }
                        }
                    }
                ]
            }
            service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()
            return True
        except Exception as e:
            print(f"Error applying status dropdown: {e}")
            return False

    def read_all_rows(self, spreadsheet_id: str) -> list[list]:
        """Reads all rows from Sheet1."""
        service = self.get_service()
        if not service:
            return []
        try:
            range_name = 'Sheet1!A:I'
            result = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=range_name
            ).execute()
            return result.get('values', [])
        except Exception as e:
            print(f"Error reading rows: {e}")
            return []

    def append_row(self, spreadsheet_id: str, row_data: list) -> bool:
        """Appends a single row to Sheet1 by updating the next empty row, preserving existing formatting and data validation."""
        service = self.get_service()
        if not service:
            return False
        try:
            rows = self.read_all_rows(spreadsheet_id)
            next_row = len(rows) + 1
            range_name = f'Sheet1!A{next_row}:I{next_row}'
            body = {'values': [row_data]}
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id, range=range_name,
                valueInputOption='USER_ENTERED', body=body
            ).execute()
            return True
        except Exception as e:
            print(f"Error appending row: {e}")
            return False

    def append_rows(self, spreadsheet_id: str, rows_data: list[list]) -> bool:
        """Appends multiple rows to Sheet1 at once, preserving formatting and validation."""
        if not rows_data:
            return True
        service = self.get_service()
        if not service:
            return False
        try:
            rows = self.read_all_rows(spreadsheet_id)
            start_row = len(rows) + 1
            end_row = start_row + len(rows_data) - 1
            range_name = f'Sheet1!A{start_row}:I{end_row}'
            body = {'values': rows_data}
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id, range=range_name,
                valueInputOption='USER_ENTERED', body=body
            ).execute()
            return True
        except Exception as e:
            print(f"Error appending batch rows: {e}")
            return False

    def update_status_and_notes(self, spreadsheet_id: str, place_id: str, status: str, notes: str) -> bool:
        """Finds row by Place ID (Column I / index 8) and updates Status (Col E) and Notes (Col G)."""
        service = self.get_service()
        if not service:
            return False
        try:
            rows = self.read_all_rows(spreadsheet_id)
            if not rows:
                return False
                
            # Find the row index where Place ID matches (Place ID is in Column I, index 8)
            row_idx = -1
            for idx, row in enumerate(rows):
                if row and len(row) > 8 and row[8] == place_id:
                    row_idx = idx + 1 # 1-indexed for sheets
                    break
                    
            if row_idx != -1:
                # Update Status (Col D / index 3)
                service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id, range=f"Sheet1!D{row_idx}",
                    valueInputOption='USER_ENTERED', body={'values': [[status]]}
                ).execute()
                
                # Update Notes (Col F / index 5)
                service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id, range=f"Sheet1!F{row_idx}",
                    valueInputOption='USER_ENTERED', body={'values': [[notes]]}
                ).execute()
                return True
        except Exception as e:
            print(f"Error updating status and notes in Google Sheet: {e}")
        return False
