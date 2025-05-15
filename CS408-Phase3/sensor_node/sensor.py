import argparse
import json
import logging
import random
import socket
import sys
import threading
import time
from datetime import datetime, timezone


def parse_args():
    parser = argparse.ArgumentParser(description="Headless sensor node for environmental data")
    parser.add_argument("--drone_ip", type=str, default="127.0.0.1",
                        help="IP address of the Drone server")
    parser.add_argument("--drone_port", type=int, default=5000,
                        help="Port of the Drone server")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="Seconds between data transmissions")
    return parser.parse_args()


def setup_logging(sensor_id):
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [%(levelname)s] [{sensor_id}] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


class SensorNode:
    def __init__(self, sensor_id, drone_ip, drone_port, interval):
        self.sensor_id = sensor_id
        self.drone_ip = drone_ip
        self.drone_port = drone_port
        self.interval = interval
        self.socket = None
        self.should_run = threading.Event()
        self.should_run.set()

    def connect(self):
        while self.should_run.is_set():
            try:
                logging.info(f"Attempting connection to {self.drone_ip}:{self.drone_port}")
                self.socket = socket.create_connection((self.drone_ip, self.drone_port), timeout=5)
                logging.info("Connected to Drone server")
                return
            except (socket.error, socket.timeout) as e:
                logging.warning(f"Connection failed: {e}. Retrying in 5 seconds...")
                time.sleep(5)

    def send_reading(self):
        data = {
            "sensor_id": self.sensor_id,
            # Simulated readings
            "temperature": round(random.uniform(15.0, 30.0), 2),
            "humidity": round(random.uniform(30.0, 70.0), 2),
            # UTC timestamp
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        payload = json.dumps(data).encode('utf-8') + b"\n"
        try:
            self.socket.sendall(payload)
            logging.info(f"Sent data: {data}")
        except socket.error as e:
            logging.error(f"Send failed: {e}")
            self.handle_disconnect()

    def handle_disconnect(self):
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
        self.socket = None
        logging.info("Disconnected from Drone server")
        self.connect()

    def run(self):
        self.connect()
        while self.should_run.is_set():
            self.send_reading()
            time.sleep(self.interval)

    def stop(self):
        self.should_run.clear()
        if self.socket:
            self.socket.close()
        logging.info("Sensor node stopped")
s

if __name__ == "__main__":
    args = parse_args()
    sensor_id = f"sensor_{random.randint(1000, 9999)}"
    setup_logging(sensor_id)

    node = SensorNode(sensor_id, args.drone_ip, args.drone_port, args.interval)
    try:
        node.run()
    except KeyboardInterrupt:
        node.stop()
        sys.exit(0)
