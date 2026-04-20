#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Google Drive Setup for Vibe Alchemist V2
# Email: turtugurtu69@gmail.com
# ═══════════════════════════════════════════════════════════════

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Google Drive Setup - Vibe Alchemist V2            ║${NC}"
echo -e "${BLUE}║     Account: turtugurtu69@gmail.com                   ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if we're in the right directory
if [ ! -f "requirements.txt" ]; then
    echo -e "${RED}ERROR: Run this from the vibe_alchemist_v2 directory${NC}"
    exit 1
fi

if [ ! -f "credentials.json" ]; then
    echo -e "${RED}ERROR: credentials.json not found in $(pwd)${NC}"
    echo "Please download your OAuth client JSON and rename it to credentials.json"
    exit 1
fi

echo -e "${YELLOW}Step 3: Authenticate and Configure Folder${NC}"
echo ""

# Create a temporary python file to handle the setup (allows input() to work)
cat << 'EOF' > drive_setup_tmp.py
import os
import sys
import logging
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Suppress warnings
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR)

SCOPES = ['https://www.googleapis.com/auth/drive.file']
TOKEN_FILE = 'token.json'
CREDENTIALS_FILE = 'credentials.json'

creds = None
if os.path.exists(TOKEN_FILE):
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    except Exception:
        creds = None

if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None 
    if not creds:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True)
    with open(TOKEN_FILE, 'w') as token:
        token.write(creds.to_json())

service = build('drive', 'v3', credentials=creds)

# 1. Try to find existing folders (created by this app)
results = service.files().list(
    q="mimeType='application/vnd.google-apps.folder' and trashed=false",
    pageSize=10,
    fields='files(id, name)'
).execute()
folders = results.get('files', [])

folder_id = None

if not folders:
    print("\nNo app-accessible folders found.")
    print("Due to security (drive.file scope), I cannot see folders you created manually.")
    choice = input("\nWould you like me to create a new 'VibeAlchemist_Faces' folder for you? (y/n): ")
    if choice.lower() == 'y':
        file_metadata = {
            'name': 'VibeAlchemist_Faces',
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = service.files().create(body=file_metadata, fields='id').execute()
        folder_id = folder.get('id')
        print(f"Successfully created folder! ID: {folder_id}")
    else:
        print("Setup aborted. You must provide a folder ID manually in .env")
        sys.exit(0)
else:
    print("\nAccessible folders:")
    for i, f in enumerate(folders):
        print(f"  [{i}] {f['name']} (ID: {f['id']})")
    
    idx = input(f"\nSelect a folder [0-{len(folders)-1}] or press Enter to create new: ")
    if idx.strip() == "":
        file_metadata = {'name': 'VibeAlchemist_Faces', 'mimeType': 'application/vnd.google-apps.folder'}
        folder = service.files().create(body=file_metadata, fields='id').execute()
        folder_id = folder.get('id')
        print(f"Created folder! ID: {folder_id}")
    else:
        try:
            folder_id = folders[int(idx)]['id']
        except (ValueError, IndexError):
            print("Invalid selection. Aborting.")
            sys.exit(1)

# 2. Update .env automatically
if folder_id:
    env_path = ".env"
    lines = []
    found = False
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if line.startswith("GDRIVE_FOLDER_ID="):
                    lines.append(f"GDRIVE_FOLDER_ID={folder_id}\n")
                    found = True
                else:
                    lines.append(line)
    
    if not found:
        lines.append(f"\nGDRIVE_FOLDER_ID={folder_id}\n")
    
    with open(env_path, 'w') as f:
        f.writelines(lines)
    
    print(f"\n✅ Updated .env with GDRIVE_FOLDER_ID={folder_id}")
EOF

# Run the temporary script
venv/bin/python drive_setup_tmp.py

# Cleanup
rm drive_setup_tmp.py

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN} Google Drive setup complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Next steps:"
echo "  1. Restart the server: ./run.sh"
echo "  2. The system will now automatically sync faces to Drive."
