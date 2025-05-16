import os
import logging
from logging.handlers import RotatingFileHandler

def setup_logging(name: str):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_path = os.path.join(log_dir, f"{name}.log")

    #file_handler = RotatingFileHandler(log_path, maxBytes=500_000, backupCount=3)
    #now overwrites logs at each exec
    file_handler = logging.FileHandler(log_path, mode='w')
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
    ))

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
    ))

    logging.basicConfig(level=logging.INFO, handlers=[file_handler, console_handler])


import argparse
import json
import logging
import socket
import threading
import time
from collections import deque
from datetime import datetime, timezone
from queue import Queue
import tkinter as tk
from tkinter import ttk, scrolledtext

def parse_args():
    parser = argparse.ArgumentParser(
        description="Drone edge server for sensor data processing and forwarding")
    parser.add_argument("--drone_port", type=int, default=5000,
                        help="Port to listen for sensor nodes")
    parser.add_argument("--central_ip", type=str, default="127.0.0.1",
                        help="Central Server IP")
    parser.add_argument("--central_port", type=int, default=6000,
                        help="Central Server port")
    parser.add_argument("--battery_threshold", type=float, default=20.0,
                        help="Battery % threshold for return-to-base")
    parser.add_argument("--forward_interval", type=float, default=5.0,
                        help="Seconds between forwards to Central Server")
    parser.add_argument("--rolling_window", type=int, default=10,
                        help="Number of readings for rolling average")
    return parser.parse_args()


class DroneEdge:
    def __init__(self, port, central_ip, central_port,
                 battery_threshold, forward_interval, rolling_window):
        self.port = port
        self.central_ip = central_ip
        self.central_port = central_port
        self.battery_threshold = battery_threshold
        self.forward_interval = forward_interval
        self.rolling_window = rolling_window

        self.sensor_data = Queue()
        self.readings = deque(maxlen=rolling_window)
        self.anomalies = []
        self.battery = 100.0
        self.returning = False
        self.forward_queue = []
        self.lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._start_sensor_server, daemon=True).start()
        threading.Thread(target=self._process_loop, daemon=True).start()
        threading.Thread(target=self._battery_simulation, daemon=True).start()
        threading.Thread(target=self._forward_loop, daemon=True).start()

    def _start_sensor_server(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("", self.port))
        srv.listen()
        logging.info(f"Drone listening for sensors on port {self.port}")
        while True:
            conn, addr = srv.accept()
            logging.info(f"Sensor connected: {addr}")
            threading.Thread(
                target=self._handle_sensor,
                args=(conn,),
                daemon=True
            ).start()

    def _handle_sensor(self, conn):
        with conn:
            buf = b""
            while True:
                data = conn.recv(1024)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        reading = json.loads(line.decode("utf-8"))
                        with self.lock:
                            self.sensor_data.put(reading)
                            self.readings.append(reading)
                        logging.info(f"Received: {reading}")
                    except json.JSONDecodeError:
                        logging.warning("Invalid JSON from sensor")
            logging.info("Sensor disconnected")

    def _process_loop(self):
        while True:
            try:
                reading = self.sensor_data.get(timeout=1)
            except:
                continue
            with self.lock:
                if self.readings:
                    temps = [r["temperature"] for r in self.readings]
                    hums = [r["humidity"] for r in self.readings]
                    avg_temp = sum(temps) / len(temps)
                    avg_humid = sum(hums) / len(hums)
                else:
                    avg_temp = avg_humid = 0.0

                # Anomaly detection
                if (reading["temperature"] < -10 or reading["temperature"] > 60 or
                    reading["humidity"] < 0 or reading["humidity"] > 100):
                    anomaly = {**reading, "type": "anomaly"}
                    self.anomalies.append(anomaly)
                    logging.warning(f"Anomaly detected: {anomaly}")

                summary = {
                    "avg_temp": round(avg_temp, 2),
                    "avg_humid": round(avg_humid, 2),
                    "last_update": datetime.now(timezone.utc).isoformat()
                }
                if not self.returning:
                    self.forward_queue.append(summary)
            time.sleep(0.1)

    def _battery_simulation(self):
        while True:
            time.sleep(1)
            with self.lock:
                self.battery = max(0.0, self.battery - 0.5)
                if self.battery <= self.battery_threshold and not self.returning:
                    self.returning = True
                    logging.warning("Battery low: returning to base")

    def _forward_loop(self):
        while True:
            time.sleep(self.forward_interval)
            with self.lock:
                if not self.returning and self.forward_queue:
                    batch = list(self.forward_queue)
                    try:
                        self._send_to_central(batch)
                        self.forward_queue.clear()
                    except Exception as e:
                        logging.error(f"Forward failed: {e}")

    def _send_to_central(self, data_batch):
        payload = json.dumps({"batch": data_batch}).encode("utf-8") + b"\n"
        with socket.create_connection(
            (self.central_ip, self.central_port), timeout=5
        ) as sock:
            sock.sendall(payload)
        logging.info(f"Forwarded {len(data_batch)} summaries to Central Server")

class DroneGUI:
    def __init__(self, drone: DroneEdge):
        self.drone = drone
        self.root = tk.Tk()
        self.root.title("Drone Edge GUI")
        self._build_ui()
        self._schedule_update()

    def _build_ui(self):
        control = ttk.Frame(self.root)
        control.pack(fill="x", padx=5, pady=5)

        self.slider = tk.Scale(
            control, from_=0, to=100, orient="horizontal",
            label="Battery Threshold (%)", command=self._on_threshold_change
        )
        self.slider.set(self.drone.battery_threshold)
        self.slider.pack(side="left", padx=(0, 10))

        ttk.Button(
            control, text="Reset Battery", command=self._reset_battery
        ).pack(side="left")

        # Status
        status = ttk.Frame(self.root)
        status.pack(fill="x", padx=5, pady=5)
        self.batt_var = tk.StringVar()
        ttk.Label(status, textvariable=self.batt_var).pack(side="left")
        self.stat_var = tk.StringVar()
        ttk.Label(status, textvariable=self.stat_var).pack(
            side="left", padx=(10, 0)
        )

        # Aggregates
        agg = ttk.Frame(self.root)
        agg.pack(fill="x", padx=5, pady=5)
        self.avg_temp = tk.StringVar()
        self.avg_hum = tk.StringVar()
        ttk.Label(agg, textvariable=self.avg_temp).pack(
            side="left", padx=(0, 15)
        )
        ttk.Label(agg, textvariable=self.avg_hum).pack(side="left")

        # Data table
        table = ttk.Frame(self.root)
        table.pack(fill="both", expand=True, padx=5, pady=5)
        cols = ("sensor_id", "temperature", "humidity", "timestamp")
        self.tree = ttk.Treeview(
            table, columns=cols, show="headings", height=8
        )
        for c in cols:
            self.tree.heading(c, text=c.replace("_", " ").title())
            self.tree.column(c, width=100, anchor="center")
        self.tree.pack(side="left", fill="both", expand=True)

        sc = ttk.Scrollbar(
            table, orient="vertical", command=self.tree.yview
        )
        self.tree.configure(yscroll=sc.set)
        sc.pack(side="right", fill="y")

        # Anomalies
        ttk.Label(self.root, text="Anomalies:").pack(
            anchor="w", padx=5
        )
        self.ano = scrolledtext.ScrolledText(self.root, height=5)
        self.ano.pack(fill="both", padx=5, pady=5)

        # Logs
        ttk.Label(self.root, text="Logs:").pack(anchor="w", padx=5)
        self.log = scrolledtext.ScrolledText(self.root, height=10)
        self.log.pack(fill="both", padx=5, pady=5)
        self._hook_logging()

    def _on_threshold_change(self, val):
        with self.drone.lock:
            self.drone.battery_threshold = float(val)
        logging.info(f"Battery threshold set to {val}% via GUI")

    def _reset_battery(self):
        with self.drone.lock:
            self.drone.battery = 100.0
            self.drone.returning = False
        logging.info("Battery reset to 100% via GUI")

    def _hook_logging(self):
        class TextHandler(logging.Handler):
            def __init__(self, widget):
                super().__init__()
                self.widget = widget
            def emit(self, record):
                msg = self.format(record) + "\n"
                self.widget.insert(tk.END, msg)
                self.widget.see(tk.END)
        h = TextHandler(self.log)
        h.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"
        ))
        logging.getLogger().addHandler(h)

    def _schedule_update(self):
        with self.drone.lock:
            # Status
            self.batt_var.set(
                f"Battery: {self.drone.battery:.1f}%"
            )
            self.stat_var.set(
                "Status: Returning to base"
                if self.drone.returning else "Status: Active"
            )
            # Aggregates
            temps = [r["temperature"] for r in self.drone.readings]
            hums = [r["humidity"] for r in self.drone.readings]
            if temps:
                self.avg_temp.set(
                    f"Avg Temp: {sum(temps)/len(temps):.2f}°C"
                )
                self.avg_hum.set(
                    f"Avg Humid: {sum(hums)/len(hums):.2f}%"
                )
            # Table
            for i in self.tree.get_children():
                self.tree.delete(i)
            for r in list(self.drone.readings):
                self.tree.insert(
                    "", "end",
                    values=(
                        r["sensor_id"],
                        r["temperature"],
                        r["humidity"],
                        r["timestamp"]
                    )
                )
            # Anomalies
            self.ano.delete("1.0", tk.END)
            for a in self.drone.anomalies[-10:]:
                self.ano.insert(tk.END, f"{a}\n")

        self.root.after(1000, self._schedule_update)

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    args = parse_args()
    setup_logging("drone")
    logging.info("Drone edge server started")
    #setup_logging()
    drone = DroneEdge(
        args.drone_port, args.central_ip, args.central_port,
        args.battery_threshold, args.forward_interval,
        args.rolling_window
    )
    drone.start()
    DroneGUI(drone).run()
