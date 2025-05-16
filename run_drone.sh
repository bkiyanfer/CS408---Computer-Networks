#!/bin/bash
echo "Starting Drone Edge Server..."
python3 drone_edge/drone.py --drone_port 5000 --central_ip 127.0.0.1 --central_port 6000
