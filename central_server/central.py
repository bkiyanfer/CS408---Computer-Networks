import os
import logging
from logging.handlers import RotatingFileHandler

def setup_logging(name: str):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_path = os.path.join(log_dir, f"{name}.log")

    file_handler = RotatingFileHandler(log_path, maxBytes=500_000, backupCount=3)
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
import tkinter as tk
from tkinter import ttk, scrolledtext
from datetime import datetime, timezone

def parse_args():
    parser = argparse.ArgumentParser(
        description="Central server to receive processed data from Drone"
    )
    parser.add_argument("--listen_ip", type=str, default="",
                        help="IP to bind the server (default all interfaces)")
    parser.add_argument("--listen_port", type=int, default=6000,
                        help="Port to listen for Drone messages")
    return parser.parse_args()


class CentralServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.data_records = []
        self.anomalies = []
        self.lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._start_server, daemon=True).start()

    def _start_server(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen()
        logging.info(f"Central Server listening on {self.host}:{self.port}")
        while True:
            conn, addr = srv.accept()
            logging.info(f"Drone connected: {addr}")
            threading.Thread(
                target=self._handle_drone, args=(conn,), daemon=True
            ).start()

    def _handle_drone(self, conn):
        with conn:
            buf = b""
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        message = json.loads(line.decode("utf-8"))
                        self._process_message(message)
                    except json.JSONDecodeError:
                        logging.warning("Invalid JSON from Drone")
        logging.info("Drone disconnected")

    def _process_message(self, message):
        batch = message.get("batch", [])
        with self.lock:
            for item in batch:
                if item.get("type") == "anomaly":
                    self.anomalies.append(item)
                    logging.warning(f"Anomaly received: {item}")
                else:
                    record = {
                        "timestamp": item.get(
                            "last_update",
                            datetime.now(timezone.utc).isoformat()
                        ),
                        "avg_temp": item.get("avg_temp"),
                        "avg_humid": item.get("avg_humid")
                    }
                    self.data_records.append(record)
                    logging.info(f"Summary received: {record}")

class CentralGUI:
    def __init__(self, server: CentralServer):
        self.server = server
        self.root = tk.Tk()
        self.root.title("Central Server GUI")
        self._build_ui()
        self._schedule_update()

    def _build_ui(self):
        frame = ttk.Frame(self.root)
        frame.pack(fill="both", expand=True, padx=5, pady=5)
        cols = ("timestamp", "avg_temp", "avg_humid")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=c.replace("_", " ").title())
            self.tree.column(c, width=120, anchor="center")
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=sb.set)
        sb.pack(side="right", fill="y")

        ttk.Label(self.root, text="Anomalies:").pack(anchor="w", padx=5)
        self.ano_box = scrolledtext.ScrolledText(self.root, height=5)
        self.ano_box.pack(fill="both", padx=5, pady=5)

        ttk.Label(self.root, text="Logs:").pack(anchor="w", padx=5)
        self.log_box = scrolledtext.ScrolledText(self.root, height=10)
        self.log_box.pack(fill="both", padx=5, pady=5)
        self._hook_logging()

    def _hook_logging(self):
        class TextHandler(logging.Handler):
            def __init__(self, widget):
                super().__init__()
                self.widget = widget
            def emit(self, record):
                msg = self.format(record) + "\n"
                self.widget.insert(tk.END, msg)
                self.widget.see(tk.END)
        h = TextHandler(self.log_box)
        h.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"
        ))
        logging.getLogger().addHandler(h)

    def _schedule_update(self):
        with self.server.lock:
            # Refresh table
            for i in self.tree.get_children():
                self.tree.delete(i)
            for rec in self.server.data_records[-50:]:
                self.tree.insert(
                    "", "end",
                    values=(rec["timestamp"], rec["avg_temp"], rec["avg_humid"])
                )
            # Refresh anomalies
            self.ano_box.delete("1.0", tk.END)
            for a in self.server.anomalies[-10:]:
                self.ano_box.insert(tk.END, f"{a}\n")
        self.root.after(1000, self._schedule_update)

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    args = parse_args()
    setup_logging("central")
    logging.info("Central server started")
    #setup_logging()
    server = CentralServer(args.listen_ip, args.listen_port)
    server.start()
    CentralGUI(server).run()
