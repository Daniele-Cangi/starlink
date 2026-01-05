import asyncio
import zmq
import zmq.asyncio
import json
import logging
import websockets
from websockets.exceptions import ConnectionClosed

# CONFIGURAZIONE
ZMQ_INPUT_URI = "tcp://127.0.0.1:5555" # Ascolta lo stesso stream del Solver (Raw Bursts)
# In produzione, ascolterebbe ANCHE l'output del Solver (Coordinate Target) su un'altra porta.

WS_PORT = 8765

logging.basicConfig(level=logging.INFO, format='%(asctime)s | BRIDGE | %(message)s')

class TacticalBridge:
    def __init__(self):
        self.ctx = zmq.asyncio.Context()
        self.sock = self.ctx.socket(zmq.SUB)
        self.sock.connect(ZMQ_INPUT_URI)       # 5555: Raw Pings
        self.sock.connect("tcp://127.0.0.1:5556") # 5556: C2 Target Fixes
        self.sock.setsockopt_string(zmq.SUBSCRIBE, "")
        
        self.clients = set()

    async def zmq_consumer(self):
        """Consuma dati dalla rete TDOA e li prepara per il broadcast"""
        logging.info(f"Connected to ZMQ Grid at {ZMQ_INPUT_URI}")
        
        while True:
            try:
                # Ricezione Non-bloccante dal bus ZMQ
                msg = await self.sock.recv_string()
                data = json.loads(msg)
                
                # Arricchimento dati (se necessario) o filtraggio
                # Qui passiamo tutto al frontend per la visualizzazione "Raw"
                
                # Broadcast ai client WebSocket connessi
                if self.clients:
                    # Serializza e invia a tutti (Fire & Forget)
                    payload = json.dumps(data)
                    await asyncio.gather(
                        *[client.send(payload) for client in self.clients],
                        return_exceptions=True
                    )
                    
            except Exception as e:
                logging.error(f"ZMQ Error: {e}")
                await asyncio.sleep(0.1)

    async def ws_handler(self, websocket):
        """Gestisce le connessioni dei browser (Dashboard)"""
        logging.info("New Dashboard Connected")
        self.clients.add(websocket)
        try:
            await websocket.wait_closed()
        finally:
            self.clients.remove(websocket)
            logging.info("Dashboard Disconnected")

    async def run(self):
        # Avvia Server WebSocket
        async with websockets.serve(self.ws_handler, "localhost", WS_PORT):
            logging.info(f"WebSocket Bridge Online on port {WS_PORT}")
            # Avvia consumatore ZMQ in background
            await self.zmq_consumer()

if __name__ == "__main__":
    bridge = TacticalBridge()
    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        pass
