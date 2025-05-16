#!/bin/bash
echo "Starting Central Server..."
python3 central_server/central.py --listen_ip 127.0.0.1 --listen_port 6000
