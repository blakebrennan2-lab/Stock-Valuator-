#!/bin/zsh
# Wrapper the scheduler calls: cd into the project and run the pipeline,
# appending output to a dated log. Keeps launchd config simple.
cd /Users/blakebrennan/Desktop/Stock-Valuator || exit 1
echo "===== run $(date '+%Y-%m-%d %H:%M:%S') =====" >> output/schedule.log
/usr/bin/python3 run_pipeline.py >> output/schedule.log 2>&1
