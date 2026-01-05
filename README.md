# STARLINK BEAM HUNTER (SIS-PRO)
> **Passive Bistatic Radar & TDOA Network for LEO Mega-Constellations**

## 📡 Overview
**Starlink Beam Hunter** is an advanced signal intelligence (SIGINT) system designed to map high-value ground targets by analyzing the Beam Hopping behavior of Starlink satellites (Ku-band, 10.7-12.7 GHz).

Instead of decrypting the payload (impossible), this system inverts the logic: **"What is the satellite looking at?"**
By combining **Distributed TDOA (Time Difference of Arrival)** with **GPU-accelerated Dwell Time Detection**, we can triangulate sectors receiving prioritized bandwidth (VIP Targets) with <100m precision.

## 🏗 Architecture
The system is composed of 4 modules communicating via **ZeroMQ**:

### 1. The Predator Node (C++20 / CUDA)
*   **Role**: Physical Layer & Signal Processing.
*   **Hardware**: USRP x310/x410 + GPSDO (for <50ns sync).
*   **Tech**: UHD Driver, cuFFT, Custom CUDA Kernels.
*   **Function**: Scans 240MHz channels, detects OFDM micro-bursts, calculates Dwell Time, stamps with FPGA Precision Time.

### 2. C2 Solver Engine (Python / SciPy)
*   **Role**: Central Brain / Mathematics.
*   **Input**: Stream of TDOA Pings from 3+ distributed nodes via ZMQ (Port 5555).
*   **Algo**: Non-Linear Least Squares minimization (Levenberg-Marquardt) on 3D ECEF coordinates.
*   **Constraint**: Earth Surface Geometry (Altitude ~ Sea Level).
*   **Output**: Lat/Lon/Alt of the confirmed emitter (Port 5556).

### 3. Blind Spot Tracker (Python)
*   **Role**: Tactical Intelligence / Density Mapping.
*   **Function**: Aggregates C2 solutions over time to build a "Heatmap" of persistent activity.
*   **Viz**: Real-time ASCII Grid for low-latency headerless operation.

### 4. God's Eye Dashboard (HTML5 / WebGL)
*   **Role**: Visualization.
*   **Tech**: Deck.gl, MapLibre, WebSockets.
*   **Function**: Renders 3D tactical map with sensorlines, active beams, and confirm target locks.

---

## 🚀 Quick Start (Simulation Mode)
To verify the mathematics without deploying physical USRPs, use the included `injector.py`.

### Prerequisites
*   Python 3.10+
*   `pip install -r requirements.txt` (scipy, pymap3d, zmq, websockets)

### Execution Sequence
Open 4 separate terminals:

**1. Solver (The Brain)** - *Must start first to bind SUB*
```bash
python src/c2_solver.py
```

**2. Tracker (The Map)**
```bash
python src/blind_spot_tracker.py
```

**3. Bridge (The Link)**
```bash
python src/viz/c2_bridge.py
```

**4. Injector (The Sim)**
```bash
python src/injector.py
```

**5. Dashboard**
Open `src/viz/dashboard.html` in your web browser.

---

## 🛠 Operations Manual: Physical USRP Deployment

This section details how to deploy the system with actual RF hardware. The simulation injector is replaced by 3 or more physical nodes running the C++ capture engine.

### 1. Hardware Requirements per Node
*   **SDR**: Ettus Research USRP X310 or X410 (High Bandwidth required).
*   **Daughterboard**: UBX-160 (10MHz - 6GHz) or TwinRX. *Note: For Ku-Band (11GHz), you need an external Downconverter (LNB) to shift 11GHz -> 1-2GHz IF.*
*   **Clock Sync**: **GPSDO (GPS Disciplined Oscillator)** Module is MANDATORY.
    *   *Without GPSDO, the TDOA math will fail due to clock drift.*
*   **Antenna**: Ku-Band Satellite Dish or Horn Antenna pointed at the visible sky shell (Shell 1: 53° Inclination).

### 2. USRP Network Configuration
Set static IPs for your devices. Recommended topology is 10GbE for IQ streaming.
*   Node Alpha: `192.168.10.2`
*   Node Beta: `192.168.10.3`
*   Node Gamma: `192.168.10.4`

Verify connectivity and GPS Lock:
```bash
uhd_usrp_probe --args="addr=192.168.10.2"
# Check for:
#   |   |       ref_locked: true
#   |   |       gps_locked: true
```

### 3. Compilation (C++ Node)
You must compile the `starlink_hunter` executable on each sensor node (Host PC connected to USRP).

```bash
mkdir build && cd build
cmake ..
make -j4
```

### 4. Running the Hunt
Execute the binary. The node will automatically hold unti GPS Lock is confirmed.

```bash
./starlink_hunter
```

**System Behavior:**
1.  **[INIT]**: Connects to USRP.
2.  **[SYNC]**: Sets Clock/Time source to GPSDO. Waits for PPS (Pulse Per Second) alignment.
3.  **[HUNT]**: Begins streaming IQ to the GPU.
4.  **[DETECT]**: When the GPU Kernel detects a Beam Dwell >1ms, it extracts the FPGA Timestamp.
5.  **[TX]**: Sends a lightweight JSON TDOA Ping via ZMQ over the internet to the C2 Server IP.

### 5. Geometry Guidelines
For best TDOA accuracy (<100m):
*   **Separation**: Place sensors at least 10-50km apart (Valid Baseline).
*   **Geometry**: Avoid placing sensors in a straight line (collinear). A triangle configuration is optimal.
*   **Time-Sync**: Ensure all nodes have clear view of the sky for GPS.

---

## ⚠️ Disclaimer
This tool uses **passive analysis** of RF physical characteristics. It does not attempt to demodulate, decode, or break the encryption of Starlink user data.
**For Educational and Research Purposes Only.**
