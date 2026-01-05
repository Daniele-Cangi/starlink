import zmq
import json
import numpy as np
import pymap3d as pm # Richiede: pip install pymap3d
from scipy.optimize import least_squares
from collections import defaultdict, deque
import time
import logging

# CONFIGURAZIONE LOGGING TATTICO
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger("C2_SOLVER")

# CONFIGURAZIONE SENSORI (POSIZIONI NOTE)
# In produzione, queste arrivano dal config DB.
# Esempio: 3 Nodi posizionati a triangolo (distanza ~50-100km)
SENSORS = {
    "ALPHA_01": {"lat": 41.9028, "lon": 12.4964, "alt": 50},   # Roma Centro
    "BETA_02":  {"lat": 41.8000, "lon": 12.6000, "alt": 300},  # Frascati (Collina)
    "GAMMA_03": {"lat": 42.0000, "lon": 12.3000, "alt": 10},   # Fiumicino (Costa)
}

# VELOCITÀ LUCE (m/ns)
C_NS = 0.299792458

class TDOASolver:
    def __init__(self):
        self.context = zmq.Context()
        self.socket_sub = self.context.socket(zmq.SUB)
        self.socket_sub.connect("tcp://127.0.0.1:5555") # Input: Connect to Injector
        self.socket_sub.setsockopt_string(zmq.SUBSCRIBE, "")
        
        self.socket_pub = self.context.socket(zmq.PUB)
        self.socket_pub.bind("tcp://*:5556") # Output: Tracker/Dashboard
        
        # Buffer di correlazione: raggruppa pings per "tempo approssimativo"
        # Key: TimeBucket (100ms), Value: List of Pings
        self.event_buffer = defaultdict(list)
        
        # Cache posizioni sensori in ECEF (Earth-Centered Earth-Fixed)
        self.sensor_ecef = {}
        self._precalc_sensor_positions()

    def _precalc_sensor_positions(self):
        """Converte Lat/Lon sensori in coordinate Cartesiane ECEF (X,Y,Z metri)"""
        for node_id, pos in SENSORS.items():
            x, y, z = pm.geodetic2ecef(pos['lat'], pos['lon'], pos['alt'])
            self.sensor_ecef[node_id] = np.array([x, y, z])
            logger.info(f"Sensor {node_id} registered at ECEF: {int(x)}, {int(y)}, {int(z)}")

    def tdoa_error_function(self, target_guess_ecef, timestamps, sensors_ecef, ref_idx):
        """
        Funzione di errore da minimizzare (Residuals).
        Calcola la differenza tra il TDOA osservato e quello teorico per la posizione ipotizzata.
        """
        x, y, z = target_guess_ecef
        residuals = []
        
        # Sensore di riferimento (di solito quello col timestamp più basso/primo arrivato)
        ref_sensor_pos = sensors_ecef[ref_idx]
        ref_time = timestamps[ref_idx]
        
        # Distanza Target -> Reference Sensor
        dist_ref = np.linalg.norm(np.array([x, y, z]) - ref_sensor_pos)
        
        for i in range(len(timestamps)):
            if i == ref_idx: continue
            
            sensor_pos = sensors_ecef[i]
            meas_time = timestamps[i]
            
            # Distanza Target -> Sensore i
            dist_i = np.linalg.norm(np.array([x, y, z]) - sensor_pos)
            
            # TDOA Teorico (distanza in metri)
            tdoa_dist_theoretical = dist_i - dist_ref
            
            # TDOA Osservato (tempo * c)
            # Delta t in nanosecondi -> metri
            tdoa_dist_measured = (meas_time - ref_time) * C_NS
            
            # Residuo = Differenza tra teoria e realtà
            residuals.append(tdoa_dist_theoretical - tdoa_dist_measured)
        
        # --- EARTH CONSTRAINT ---
        # Con 3 sensori abbiamo solo 2 equazioni TDOA indipendenti per 3 incognite (x,y,z).
        # Aggiungiamo un vincolo "soft": Il target si trova sulla superficie terrestre (Alt ~ 0).
        # Questo porta il numero di residui a 3, rendendo il sistema risolvibile.
        _, _, alt_est = pm.ecef2geodetic(x, y, z)
        residuals.append(alt_est - 10.0) # Assumiamo target a 10m di quota (livello mare/terra)
            
        return np.array(residuals)

    def solve_position(self, pings):
        """
        Esegue il Solver Non-Lineare Least Squares.
        Input: Lista di dict {'node_id': str, 'timestamp_ns': int}
        """
        if len(pings) < 3:
            logger.warning(f"Not enough sensors for 2D fix (Got {len(pings)}, Need 3+)")
            return None

        # Preparazione dati
        sorted_pings = sorted(pings, key=lambda x: x['timestamp_ns'])
        ref_ping = sorted_pings[0] # Il primo che ha sentito il burst è il riferimento
        
        timestamps = np.array([p['timestamp_ns'] for p in sorted_pings], dtype=np.float64)
        sensor_coords = np.array([self.sensor_ecef[p['node_id']] for p in sorted_pings])
        
        # Initial Guess (Barycenter of sensors + Earth surface projection)
        # Partiamo dal centroide dei sensori come ipotesi iniziale
        initial_guess = np.mean(sensor_coords, axis=0)
        
        # --- SOLVER ---
        # Usiamo Levenberg-Marquardt o Trust Region Reflective
        result = least_squares(
            self.tdoa_error_function,
            initial_guess,
            args=(timestamps, sensor_coords, 0), # 0 è l'indice del reference (sorted)
            method='lm',
            ftol=1e-6 # Alta precisione
        )
        
        if result.success:
            final_ecef = result.x
            # Riconversione ECEF -> Geodetic (Lat/Lon)
            lat, lon, alt = pm.ecef2geodetic(final_ecef[0], final_ecef[1], final_ecef[2])
            
            # Sanity Check (Altitude non deve essere nello spazio o sottoterra per terminali terrestri)
            # Se alt > 15km è probabilmente un aereo o errore. Se < -500m è errore.
            return {"lat": lat, "lon": lon, "alt": alt, "error_cost": result.cost}
        else:
            logger.error("Solver failed to converge")
            return None

    def run(self):
        logger.info("TDOA C2 ENGINE ONLINE - WAITING FOR BURSTS...")
        
        while True:
            try:
                # 1. Ricezione Pacchetto ZMQ
                msg = self.socket_sub.recv()
                data = json.loads(msg)
                
                # 2. Correlazione Temporale
                # Usiamo il timestamp diviso per 100ms (1e8 ns) come "Bucket ID"
                # Questo raggruppa eventi vicini nel tempo.
                # Nota: In produzione serve logica sliding window più robusta per eventi al bordo.
                bucket_id = int(data['timestamp_ns'] / 1e8) 
                
                self.event_buffer[bucket_id].append(data)
                
                # Check se il bucket è "maturo" (es. abbiamo 3 nodi o è passato tempo)
                # Semplificazione: Se abbiamo 3 nodi distinti nel bucket, tentiamo il solve
                current_bucket = self.event_buffer[bucket_id]
                unique_nodes = set(p['node_id'] for p in current_bucket)
                
                if len(unique_nodes) >= 3:
                    logger.info(f"Target Acquired! Triangulating with {len(unique_nodes)} nodes...")
                    
                    solution = self.solve_position(current_bucket)
                    
                    if solution:
                        logger.info("\033[1;41m[TARGET FIX CONFIRMED]\033[0m")
                        logger.info(f"  > LAT: {solution['lat']:.6f}")
                        logger.info(f"  > LON: {solution['lon']:.6f}")
                        logger.info(f"  > ALT: {solution['alt']:.1f} m")
                        logger.info(f"  > Accuracy Cost: {solution['error_cost']:.4f}")
                        
                        # Dispatch to Dashboard/Tracker
                        solution["type"] = "TARGET_FIX" # Protocol Compliance
                        self.socket_pub.send_string(json.dumps(solution))
                    
                    # Cleanup bucket (evita doppi solve)
                    del self.event_buffer[bucket_id]

            except Exception as e:
                logger.error(f"Processing Error: {e}")

if __name__ == "__main__":
    solver = TDOASolver()
    solver.run()
