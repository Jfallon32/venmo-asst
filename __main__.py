import os
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from venmo_api import Client
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

def main():
    # Prompt the user for Venmo username, password, and spreadsheet link
    venmo_username = input("Enter your Venmo username: ")
    venmo_password = input("Enter your Venmo password: ")
    spreadsheet_link = input("Enter the Google Sheets link: ")
    access_token = Client.get_access_token(username=venmo_username, password=venmo_password)

    # Initialize Venmo client
    client = Client(access_token=access_token)

    # Validate Venmo credentials
    if not client.user.get_user_transactions():
        print("Invalid Venmo username or password. Please try again.")
        return

    # Parse the spreadsheet ID from the link
    spreadsheet_id = get_spreadsheet_id(spreadsheet_link)
    if not spreadsheet_id:
        print("Invalid Google Sheets link. Please try again.")
        return

    # Set Google Sheets API credentials
    credentials_path = "/path/to/credentials.json"  # Replace with the path to your credentials file
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path

    # Authenticate and initialize Sheets API service
    service = initialize_sheets_service()

    # Retrieve Venmo transactions
    transactions = client.user.get_user_transactions()

    # Filter and process new transactions only
    new_transactions = filter_new_transactions(service, spreadsheet_id, transactions)

    # Update budget and roster with new transactions
    update_budget_and_roster(service, spreadsheet_id, new_transactions)

    print("Budget and roster successfully updated.")

def get_spreadsheet_id(link):
    # Parse the spreadsheet ID from the Google Sheets link
    parts = link.split("/")
    for part in parts:
        if part.startswith("https://docs.google.com/spreadsheets/d/"):
            return part.split("/")[-1]
    return None

def initialize_sheets_service():
    # Initialize the Sheets API service using credentials
    credentials = None
    if os.path.exists('token.json'):
        credentials = Credentials.from_authorized_user_file('token.json')
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, ['https://www.googleapis.com/auth/spreadsheets'])
            credentials = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(credentials.to_json())
    return build('sheets', 'v4', credentials=credentials)

def filter_new_transactions(service, spreadsheet_id, transactions):
    # Retrieve existing transaction IDs from the spreadsheet
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range="Sheet1!A2:A"
    ).execute()
    existing_ids = set(result.get("values", []))

    # Filter out transactions that have already been processed
    new_transactions = []
    for transaction in transactions:
        if transaction.id not in existing_ids:
            new_transactions.append(transaction)

    return new_transactions

def update_budget_and_roster(service, spreadsheet_id, transactions):
    # Prepare the values to be written to the spreadsheet
    values = []
    total_budget = 0
    roster = {}

    # Retrieve existing data from the spreadsheet
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range="Sheet1!A:G"
    ).execute()
    existing_data = result.get("values", [])

    # Find the total budget and create the roster
    for row in existing_data:
        if row and row[0] == "Total Budget":
            total_budget = float(row[1])
        elif row and row[0] != "ID":
            venmo_id = row[1]
            dues_paid = float(row[3])
            roster[venmo_id] = dues_paid

    # Process transactions and update budget and roster
    for transaction in transactions:
        note = transaction.note
        amount = transaction.amount
        sender_name = transaction.user.username
        sender_venmo_id = transaction.user.id

        if note == "dues" and amount > 0:
            if sender_venmo_id not in roster:
                roster[sender_venmo_id] = 0

            roster[sender_venmo_id] += amount
        elif amount < 0:
            total_budget += amount
            values.append([amount, note])
        elif amount > 0:
            total_budget += amount
            values.append([amount, note])

    # Write the updated roster to the spreadsheet
    roster_values = [["ID", "Venmo ID", "Name", "Dues Paid"]]
    for venmo_id, dues_paid in roster.items():
        roster_values.append([f"=ROW()+1", venmo_id, get_name_from_id(service, venmo_id), dues_paid])

    # Write the values to the sheet
    range_name = "Sheet1!D2:E" + str(1 + len(values))
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()

    # Update the total budget and roster in the spreadsheet
    range_name_budget = "Sheet1!B1:B2"
    range_name_roster = "Sheet1!A2:D" + str(1 + len(roster))

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_name_budget,
        valueInputOption="USER_ENTERED",
        body={"values": [[total_budget]]},
    ).execute()

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_name_roster,
        valueInputOption="USER_ENTERED",
        body={"values": roster_values},
    ).execute()

def get_name_from_id(service, venmo_id):
    # Retrieve user's name based on Venmo ID
    # Here, it assumes you have a separate sheet named "Roster" with ID and Name columns
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range="Roster!A:B"
    ).execute()
    values = result.get("values", [])
    for row in values:
        if row and row[0] == venmo_id:
            return row[1]
    return ""

if __name__ == "__main__":
    main()