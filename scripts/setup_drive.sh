#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Google Drive Setup for Vibe Alchemist
# Run this script to configure automatic face upload to Google Drive
# ═══════════════════════════════════════════════════════════════

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Vibe Alchemist — Google Drive Face Upload Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Step 1: Check if credentials.json already exists ──
CRED_FILE="$PROJECT_DIR/credentials.json"
if [ -f "$CRED_FILE" ]; then
    echo "✅ credentials.json already exists"
    SA_EMAIL=$(python3 -c "import json; print(json.load(open('$CRED_FILE')).get('client_email', 'unknown'))" 2>/dev/null || echo "unknown")
    echo "   Service account: $SA_EMAIL"
    echo ""
    echo "   To reconfigure: delete credentials.json and run this script again"
    echo "   rm $CRED_FILE"
    echo ""
else
    echo "📋 STEP 1: Download Service Account Credentials"
    echo ""
    echo "   1. Go to: https://console.cloud.google.com/iam-admin/serviceaccounts"
    echo "   2. Create a new service account (or use existing one)"
    echo "   3. Click on the account → Keys → Add Key → Create new key → JSON"
    echo "   4. Download the JSON file"
    echo "   5. Move it to: $CRED_FILE"
    echo ""
    echo "   After downloading, press Enter to continue..."
    read -r

    echo "   Path to credentials JSON file:"
    read -r INPUT_PATH
    INPUT_PATH=$(echo "$INPUT_PATH" | xargs)  # trim whitespace

    if [ -f "$INPUT_PATH" ]; then
        cp "$INPUT_PATH" "$CRED_FILE"
        echo "   ✅ Copied to $CRED_FILE"
    else
        echo "   ❌ File not found: $INPUT_PATH"
        exit 1
    fi
    echo ""
fi

# ── Step 2: Get the service account email ──
SA_EMAIL=$(python3 -c "import json; print(json.load(open('$CRED_FILE')).get('client_email', 'unknown'))" 2>/dev/null || echo "unknown")
PROJECT_ID=$(python3 -c "import json; print(json.load(open('$CRED_FILE')).get('project_id', 'unknown'))" 2>/dev/null || echo "unknown")

echo "📋 STEP 2: Share Google Drive Folder with Service Account"
echo ""
echo "   Service Account Email: $SA_EMAIL"
echo "   Project ID: $PROJECT_ID"
echo ""
echo "   Instructions:"
echo "   1. Open Google Drive and create a folder (e.g., 'VibeAlchemist Faces')"
echo "   2. Open the folder and copy the ID from the URL:"
echo "      https://drive.google.com/drive/folders/YOUR_FOLDER_ID_HERE"
echo "   3. Right-click the folder → Share → paste this email:"
echo "      $SA_EMAIL"
echo "   4. Give it 'Editor' access"
echo ""
echo "   Enter the Drive Folder ID (just the long string):"
read -r FOLDER_ID
FOLDER_ID=$(echo "$FOLDER_ID" | xargs)

if [ -z "$FOLDER_ID" ]; then
    echo "   ❌ Folder ID cannot be empty"
    exit 1
fi

echo ""
echo "   Updating .env with folder ID..."

# ── Step 3: Update .env ──
ENV_FILE="$PROJECT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "   ❌ .env file not found at $ENV_FILE"
    exit 1
fi

# Update or add GDRIVE_FOLDER_ID
if grep -q "^GDRIVE_FOLDER_ID=" "$ENV_FILE" 2>/dev/null; then
    # Replace existing line (handle with or without quotes)
    sed -i "s|^GDRIVE_FOLDER_ID=.*|GDRIVE_FOLDER_ID=$FOLDER_ID|" "$ENV_FILE"
    echo "   ✅ Updated GDRIVE_FOLDER_ID in .env"
else
    echo "" >> "$ENV_FILE"
    echo "GDRIVE_FOLDER_ID=$FOLDER_ID" >> "$ENV_FILE"
    echo "   ✅ Added GDRIVE_FOLDER_ID to .env"
fi

# Ensure credentials file path is set
if grep -q "^GDRIVE_CREDENTIALS_FILE=" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|^GDRIVE_CREDENTIALS_FILE=.*|GDRIVE_CREDENTIALS_FILE=credentials.json|" "$ENV_FILE"
else
    echo "GDRIVE_CREDENTIALS_FILE=credentials.json" >> "$ENV_FILE"
fi

# Ensure upload interval is set
if grep -q "^DRIVE_UPLOAD_INTERVAL=" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|^DRIVE_UPLOAD_INTERVAL=.*|DRIVE_UPLOAD_INTERVAL=300|" "$ENV_FILE"
else
    echo "DRIVE_UPLOAD_INTERVAL=300" >> "$ENV_FILE"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Drive Configuration Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Summary:"
echo "    Folder ID:   $FOLDER_ID"
echo "    Credentials: $CRED_FILE"
echo "    Service Acct: $SA_EMAIL"
echo "    Sync Interval: every 5 minutes"
echo ""
echo "  Next Steps:"
echo "    1. Restart the server:"
echo "       cd $PROJECT_DIR"
echo "       docker compose down && docker compose up -d --build"
echo ""
echo "    2. Test the connection:"
echo "       curl http://localhost:8000/api/faces/drive/test"
echo ""
echo "    3. Check status anytime:"
echo "       curl http://localhost:8000/api/faces/drive/status"
echo ""
