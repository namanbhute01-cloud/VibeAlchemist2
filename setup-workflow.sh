#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Add CI/CD workflow to GitHub repo
# Your PAT doesn't have workflow scope, so we use the GitHub API
# ═══════════════════════════════════════════════════════════════

set -e

WORKFLOW_FILE=".github/workflows/ci-cd.yml"

if [ ! -f "$WORKFLOW_FILE" ]; then
    echo "ERROR: $WORKFLOW_FILE not found"
    exit 1
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  CI/CD Workflow Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Method 1: GitHub CLI
if command -v gh &>/dev/null && gh auth status &>/dev/null 2>&1; then
    REPO=$(git remote get-url origin | sed 's/.*://' | sed 's/\.git$//')
    echo "Using GitHub CLI to add workflow to: $REPO"
    echo ""

    # Encode file content as base64
    CONTENT=$(base64 -w0 < "$WORKFLOW_FILE")
    MESSAGE="ci: add CI/CD pipeline workflow"

    gh api "repos/$REPO/contents/$WORKFLOW_FILE" \
        --method PUT \
        --field message="$MESSAGE" \
        --field content="$CONTENT" \
        --field branch=main

    echo ""
    echo "✓ Workflow added! Check: https://github.com/$REPO/actions"
    exit 0
fi

# Method 2: Manual instructions
echo "Your PAT doesn't have workflow scope to push .github/workflows/ files."
echo ""
echo "Add the workflow manually (takes 30 seconds):"
echo ""
echo "  1. Go to: https://github.com/namanbhute01-cloud/VibeAlchemist2/actions/new"
echo "  2. Click 'set up a workflow yourself'"
echo "  3. Name it: ci-cd.yml"
echo "  4. Copy the content from: $WORKFLOW_FILE"
echo "  5. Click 'Commit new file'"
echo ""
echo "Or generate a new PAT with 'workflow' scope:"
echo "  https://github.com/settings/tokens/new"
echo "  Check: repo, workflow"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Workflow file is ready at: $WORKFLOW_FILE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
