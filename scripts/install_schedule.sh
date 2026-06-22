#!/bin/zsh
# Install the every-2-days launchd job.
set -e
PROJ=/Users/blakebrennan/Desktop/Stock-Valuator
PLIST=com.stock-valuator.scan.plist
DEST="$HOME/Library/LaunchAgents/$PLIST"

chmod +x "$PROJ/scripts/run_pipeline.sh"
mkdir -p "$HOME/Library/LaunchAgents" "$PROJ/output"
cp "$PROJ/scripts/$PLIST" "$DEST"

launchctl unload "$DEST" 2>/dev/null || true
launchctl load "$DEST"

echo "Installed: $DEST"
echo "Cadence: every 2 days (StartInterval 172800s)."
echo "Verify:  launchctl list | grep stock-valuator"
echo "Test now: $PROJ/scripts/run_pipeline.sh"
launchctl list | grep stock-valuator || true
