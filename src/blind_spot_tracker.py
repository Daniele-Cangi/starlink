import zmq
import json
import time
import os
from collections import defaultdict

# ASCII HEATMAP CONFIG
GRID_LAT_START = 41.70
GRID_LON_START = 12.30
GRID_STEP = 0.05  # ~5.5km per cell
GRID_ROWS = 10
GRID_COLS = 10

class BlindSpotTracker:
    def __init__(self):
        context = zmq.Context()
        self.socket = context.socket(zmq.SUB)
        self.socket.connect("tcp://127.0.0.1:5556") # Connect to C2 Output
        self.socket.setsockopt_string(zmq.SUBSCRIBE, "")
        
        # Grid Density: (Row, Col) -> Hit Count
        self.density_map = defaultdict(int)
        
        print("[TRACKER] Blind Spot Monitor Active. Waiting for C2 data...")

    def update_grid(self, lat, lon):
        # Quantize coordinates to grid
        row = int((lat - GRID_LAT_START) / GRID_STEP)
        col = int((lon - GRID_LON_START) / GRID_STEP)
        
        if 0 <= row < GRID_ROWS and 0 <= col < GRID_COLS:
            self.density_map[(row, col)] += 1
            return True
        return False

    def render_map(self):
        # Clear screen (ANSI)
        print("\033[2J\033[H", end="")
        print("====== STARLINK BLIND SPOT TRACKER ======")
        print(f"Coverage: {GRID_LAT_START}N : {GRID_LON_START}E (Step: {GRID_STEP})")
        
        for r in range(GRID_ROWS - 1, -1, -1): # Render Top to Bottom
            line = f"{GRID_LAT_START + r*GRID_STEP:.2f} | "
            for c in range(GRID_COLS):
                hits = self.density_map[(r, c)]
                char = "."
                if hits > 0: char = "\033[92m░\033[0m" # Low
                if hits > 5: char = "\033[93m▒\033[0m" # Med
                if hits > 15: char = "\033[91m█\033[0m" # High (VIP)
                line += f"{char} "
            print(line)
        
        # X-Axis
        print("       " + "-" * (GRID_COLS * 2))
        x_axis = "       "
        for c in range(0, GRID_COLS, 2):
            x_axis += f"{GRID_LON_START + c*GRID_STEP:.2f} "
        print(x_axis)
        print("\n[LEGEND] . None  ░ Low  ▒ Med  █ VIP TARGET DETECTED")

    def run(self):
        last_render = time.time()
        while True:
            try:
                # Non-blocking check or timeout
                if self.socket.poll(timeout=100):
                    msg = self.socket.recv_string()
                    data = json.loads(msg)
                    
                    lat = data.get("lat")
                    lon = data.get("lon")
                    
                    if self.update_grid(lat, lon):
                         # Rerender on update
                        self.render_map()
                        print(f"LAST FIX: {lat:.4f}, {lon:.4f} [Alt: {data.get('alt'):.0f}m]")
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")

if __name__ == "__main__":
    tracker = BlindSpotTracker()
    tracker.run()
