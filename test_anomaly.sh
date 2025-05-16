#!/bin/bash
echo "Starting Anomaly Test Sensor..."
python3 sensor_node/sensor.py --drone_ip 127.0.0.1 --drone_port 5000 --interval 2 <<EOF
{
  "temperature": 100.0,
  "humidity": 150.0
}
EOF
