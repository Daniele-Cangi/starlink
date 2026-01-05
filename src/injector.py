import zmq
import json
import time
import numpy as np
import pymap3d as pm
import random

# CONFIGURAZIONE TARGET SEGRETO (es. Una piazza a Roma)
TARGET_TRUE = {"lat": 41.8500, "lon": 12.5500, "alt": 15}

# SENSORI (Devono matchare quelli nel C2)
SENSORS = {
    "ALPHA_01": {"lat": 41.9028, "lon": 12.4964, "alt": 50},
    "BETA_02":  {"lat": 41.8000, "lon": 12.6000, "alt": 300},
    "GAMMA_03": {"lat": 42.0000, "lon": 12.3000, "alt": 10},
}

C_NS = 0.299792458 # metri / ns

def simulate_burst():
    context = zmq.Context()
    socket = context.socket(zmq.PUB)
    socket.bind("tcp://*:5555") # Publisher BINDS
    
    # ZMQ "Slow Joiner" fix: Wait for subscribers to connect
    print("ZMQ Connecting... (Waiting 1s)")
    time.sleep(1)
    
    print(f"--- SIMULATION STARTED ---")
    print(f"Secret Target at: {TARGET_TRUE['lat']}, {TARGET_TRUE['lon']}")
    
    # 1. Converti tutto in ECEF
    tx, ty, tz = pm.geodetic2ecef(TARGET_TRUE['lat'], TARGET_TRUE['lon'], TARGET_TRUE['alt'])
    target_ecef = np.array([tx, ty, tz])
    
    # Base timestamp (es. "adesso" in nanosecondi GPS)
    base_time_ns = int(time.time() * 1e9)
    
    packets = []
    
    # 2. Calcola tempo di volo per ogni sensore
    for node_id, pos in SENSORS.items():
        sx, sy, sz = pm.geodetic2ecef(pos['lat'], pos['lon'], pos['alt'])
        sensor_ecef = np.array([sx, sy, sz])
        
        # Distanza Euclidea 3D
        dist = np.linalg.norm(target_ecef - sensor_ecef)
        
        # Tempo di volo (ns) = Distanza / c
        flight_time_ns = dist / C_NS
        
        # Arrival Time = Base + Flight Time + Jitter (Errore GPS simulato)
        # Jitter: +/- 50ns (Tipico di un buon GPSDO)
        jitter = random.gauss(0, 50) 
        arrival_time = int(base_time_ns + flight_time_ns + jitter)
        
        packets.append({
            "type": "TDOA_PING",
            "node_id": node_id,
            "timestamp_ns": arrival_time,
            "dwell_ms": 2.5,
            "freq_hz": 11325000000,
            "power_db": -60 + random.uniform(-2, 2)
        })
        
        print(f"Node {node_id}: Dist={dist/1000:.2f}km, Flight={flight_time_ns:.0f}ns")

    # 3. Invio (simula arrivo asincrono su rete)
    print("Injecting packets...")
    random.shuffle(packets) # L'ordine di arrivo in rete non è garantito
    
    for p in packets:
        socket.send_string(json.dumps(p))
        time.sleep(random.uniform(0.001, 0.010)) # 1-10ms lag di rete tra pacchetti
        
    print("Injection Complete.")

if __name__ == "__main__":
    while True:
        simulate_burst()
        time.sleep(2) # Un burst ogni 2 secondi
