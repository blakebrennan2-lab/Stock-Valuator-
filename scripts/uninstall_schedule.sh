#!/bin/zsh
# Remove the every-2-days launchd job.
PLIST=com.stock-valuator.scan.plist
DEST="$HOME/Library/LaunchAgents/$PLIST"
launchctl unload "$DEST" 2>/dev/null || true
rm -f "$DEST"
echo "Uninstalled $DEST"
