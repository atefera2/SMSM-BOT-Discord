#!/bin/bash
# ============================================================
#  Push this repo to GitHub
#
#  Double-click, or run:  bash PUSH-TO-GITHUB.command
#
#  Works two ways:
#   - If the GitHub CLI (gh) is installed, it creates the repo
#     and pushes in one step.
#   - Otherwise it prints the exact commands to copy/paste.
#
#  Your .env / token is NOT in this repo and will not be pushed.
# ============================================================

set -u
cd "$(dirname "$0")" || exit 1
REPO_NAME="smsm-festival-ops"

echo "============================================================"
echo " Pushing $REPO_NAME to GitHub"
echo "============================================================"
echo ""

# Safety: make sure nothing sensitive is tracked.
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "!! .env is tracked by git. Stopping."
  echo "!! Run:  git rm --cached .env"
  read -r -p "Press Enter to close..."; exit 1
fi
echo "[check] No .env tracked. Safe to push."
echo ""

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  git init -q -b main && git add -A && git commit -q -m "Initial commit"
fi

if command -v gh >/dev/null 2>&1; then
  echo "[1/2] GitHub CLI found."
  gh auth status >/dev/null 2>&1 || { echo "      Logging you in..."; gh auth login; }
  echo ""
  echo "[2/2] Creating the repository..."
  echo "      Private is recommended — it contains your festival's menu and"
  echo "      operating details. You can make it public later."
  read -r -p "      Private repo? [Y/n] " ANS
  VIS="--private"
  case "${ANS:-y}" in [Nn]*) VIS="--public" ;; esac
  gh repo create "$REPO_NAME" $VIS --source=. --remote=origin --push && {
    echo ""
    echo "============================================================"
    echo " Done. Repo URL:"
    gh repo view --json url -q .url
    echo ""
    echo " Send that link to your brother. Point him at:"
    echo "   README.md            what it is and how it works"
    echo "   docs/DEPLOY.md       putting it on a server"
    echo "   docs/ARCHITECTURE.md where to add features"
    echo "   docs/ROADMAP.md      what to build next"
    echo "============================================================"
  }
  read -r -p "Press Enter to close..."
  exit 0
fi

echo "GitHub CLI (gh) isn't installed. Two options:"
echo ""
echo "  EASIEST — install it, then run this script again:"
echo "      brew install gh"
echo ""
echo "  OR do it by hand:"
echo "      1. Go to  https://github.com/new"
echo "      2. Name:  $REPO_NAME"
echo "      3. Choose Private. Do NOT add a README, .gitignore, or license"
echo "         (this repo already has them)."
echo "      4. Click Create repository."
echo "      5. Copy/paste these commands here, replacing YOURNAME:"
echo ""
echo "         cd \"$(pwd)\""
echo "         git remote add origin https://github.com/YOURNAME/$REPO_NAME.git"
echo "         git branch -M main"
echo "         git push -u origin main"
echo ""
read -r -p "Press Enter to close..."
