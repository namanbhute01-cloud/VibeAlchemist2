#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Google Drive Setup for Vibe Alchemist V2
# Email: turtugurtu69@gmail.com
# ═══════════════════════════════════════════════════════════════

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Google Drive Setup - Vibe Alchemist V2            ║${NC}"
echo -e "${BLUE}║     Account: turtugurtu69@gmail.com                   ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if we're in the right directory
if [ ! -f "requirements.txt" ]; then
    echo "ERROR: Run this from the vibe_alchemist_v2 directory"
    exit 1
fi

# Install Google libraries
echo -e "${YELLOW}Installing Google Drive libraries...${NC}"
pip install --quiet google-auth google-auth-oauthlib google-api-python-client

echo ""
echo -e "${YELLOW}Step 1: Create Google Cloud Project${NC}"
echo ""
echo "  1. Go to: https://console.cloud.google.com/"
echo "  2. Sign in with: turtugurtu69@gmail.com"
echo "  3. Create a new project (or select existing)"
echo "  4. Enable 'Google Drive API'"
echo "     → APIs & Services → Library → Search 'Google Drive API' → Enable"
echo "  5. Create OAuth consent screen:"
echo "     → APIs & Services → OAuth consent screen"
echo "     → User Type: External"
echo "     → App name: Vibe Alchemist"
echo "     → User support email: turtugurtu69@gmail.com"
echo "     → Developer contact: turtugurtu69@gmail.com"
echo "     → Scopes: Add '.../auth/drive.file'"
echo "     → Test users: Add turtugurtu69@gmail.com"
echo "  6. Create credentials:"
echo "     → APIs & Services → Credentials → Create Credentials → OAuth client ID"
echo "     → Application type: Desktop app"
echo "     → Name: Vibe Alchemist"
echo "     → Download the JSON file"
echo ""

echo -e "${YELLOW}Step 2: Save credentials${NC}"
echo ""
echo "  1. Rename the downloaded file to: credentials.json"
echo "  2. Place it in: $(pwd)/credentials.json"
echo ""

read -p "Have you placed credentials.json? (y/n): " confirm

if [ "$confirm" != "y" ]; then
    echo "Run this script again after adding credentials.json"
    exit 0
fi

if [ ! -f "credentials.json" ]; then
    echo "ERROR: credentials.json not found in $(pwd)"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 3: Authenticate with Google Drive${NC}"
echo ""

# Run authentication script
venv/bin/python -c "
import os
import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = ['https://www.googleapis.com/auth/drive.file']
TOKEN_FILE = 'token.json'
CREDENTIALS_FILE = 'credentials.json'

creds = None

# Load existing token if available
if os.path.exists(TOKEN_FILE):
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

# If no valid credentials, run the flow
if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        # Use console flow for headless servers
        creds = flow.run_console()

    # Save the credentials for the future
    with open(TOKEN_FILE, 'w') as token:
        token.write(creds.to_json())

    print('Authentication successful!')
    print(f'Token saved to: {TOKEN_FILE}')

# Test Drive access
from googleapiclient.discovery import build
service = build('drive', 'v3', credentials=creds)

# List folders
results = service.files().list(
    q="mimeType='application/vnd.google-apps.folder'",
    pageSize=10,
    fields='files(id, name)'
).execute()

folders = results.get('files', [])
if folders:
    print('\\nYour Google Drive folders:')
    for f in folders:
        print(f'  {f[\"name\"]} (ID: {f[\"id\"]})')
else:
    print('\\nNo folders found in Drive')

print('\\nSetup complete! Add the folder ID to .env as GDRIVE_FOLDER_ID')
" 2>&1

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN} Google Drive setup complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Next steps:"
echo "  1. Copy the folder ID from the output above"
echo "  2. Update .env: GDRIVE_FOLDER_ID=<your_folder_id>"
echo "  3. Restart the server"
