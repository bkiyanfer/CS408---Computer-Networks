#!/bin/bash
echo "Starting 3 Sensor Nodes..."
for i in {1..3}
do
    python3 sensor_node/sensor.py --drone_ip 127.0.0.1 --drone_port 5000 --interval 2 &
done
wait
