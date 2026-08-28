#!/bin/bash
# Kill any running uvicorn on port 8000
lsof -ti :8000 | xargs kill -9 2>/dev/null
sleep 0.3

# Rotate server.log when it grows past 5MB (keep one backup: server.log.1)
if [ -f server.log ]; then
  size=$(stat -f%z server.log 2>/dev/null)
  if [ -z "$size" ]; then size=$(stat -c%s server.log 2>/dev/null); fi
  if [ -z "$size" ] || [ "$size" -gt 5242880 ]; then
    mv -f server.log server.log.1 2>/dev/null
  fi
fi

nohup python main.py > server.log 2>&1 &
echo "Server started in background (PID: $!)"
echo "Logs: tail -f server.log"
echo "Opening http://127.0.0.1:8000 ..."
sleep 1
open http://127.0.0.1:8000
