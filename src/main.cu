#include <chrono>
#include <complex>
#include <iomanip>
#include <iostream>
#include <thread>
#include <vector>


// UHD Driver
#include <uhd/usrp/multi_usrp.hpp>
#include <uhd/utils/safe_main.hpp>
#include <uhd/utils/thread.hpp>


// ZeroMQ & JSON
#include <nlohmann/json.hpp>
#include <zmq.hpp>


// Project Includes
#include "../include/starlink_defs.hpp"
#include "../kernels/beam_detector.cu"

using json = nlohmann::json;

class StarlinkHunter {
  uhd::usrp::multi_usrp::sptr usrp;
  CudaBeamScanner *gpu_scanner;
  zmq::context_t zmq_ctx;
  zmq::socket_t zmq_pub;
  std::string node_id;
  bool running = true;

public:
  StarlinkHunter() : zmq_ctx(1), zmq_pub(zmq_ctx, ZMQ_PUB) {
    node_id = "NODO_ALPHA_01"; // TODO: Load from config
    std::cout << "[INIT] Initializing Starlink Hunter TDOA Node: " << node_id
              << std::endl;

    // Setup ZeroMQ
    zmq_pub.bind("tcp://*:5555");

    // 1. Setup USRP with GPSDO
    std::string device_args("type=x300,master_clock_rate=250e6");
    usrp = uhd::usrp::multi_usrp::make(device_args);

    // SYNC STRATEGY: GPSDO + PPS
    std::cout << "[SYNC] Setting Clock Source to GPSDO..." << std::endl;
    usrp->set_clock_source("gpsdo");
    usrp->set_time_source("gpsdo");

    // Wait for GPS Lock
    check_gps_lock();

    // Sync Time to Next PPS
    std::cout << "[SYNC] Aligning FPGA time to next PPS..." << std::endl;
    usrp->set_time_unknown_pps(uhd::time_spec_t(0.0));
    std::this_thread::sleep_for(std::chrono::seconds(1)); // Allow PPS to happen

    // Configura RX
    usrp->set_rx_rate(250e6);
    usrp->set_rx_freq(starlink::KU_CHANNELS[0].center_freq);
    usrp->set_rx_gain(30.0);

    // 2. Setup GPU
    gpu_scanner = new CudaBeamScanner(1024 * 1024 * 10); // 10M samples
  }

  void check_gps_lock() {
    std::cout << "[SYNC] Waiting for GPS Lock...";
    bool locked = false;
    while (!locked && running) {
      auto sensors = usrp->get_mboard_sensor_names(0);
      if (std::find(sensors.begin(), sensors.end(), "gps_locked") !=
          sensors.end()) {
        bool gps_locked = usrp->get_mboard_sensor("gps_locked", 0).to_bool();
        bool ref_locked = usrp->get_mboard_sensor("ref_locked", 0).to_bool();
        if (gps_locked && ref_locked) {
          locked = true;
          std::cout << " LOCKED!" << std::endl;
        }
      }
      if (!locked) {
        std::cout << ".";
        std::cout.flush();
        std::this_thread::sleep_for(std::chrono::seconds(1));
      }
    }
  }

  void run_hunt() {
    std::cout << "[HUNT] TDOA Sentinel Active on Shell 1..." << std::endl;

    uhd::stream_args_t stream_args("fc32", "sc16");
    auto rx_stream = usrp->get_rx_stream(stream_args);

    uhd::stream_cmd_t stream_cmd(
        uhd::stream_cmd_t::STREAM_MODE_START_CONTINUOUS);
    stream_cmd.stream_now = true;
    rx_stream->issue_stream_cmd(stream_cmd);

    std::vector<std::complex<float>> host_buffer(1024 * 1024 * 10);
    uhd::monitor::id_type last_md;

    while (running) {
      uhd::rx_metadata_t md;
      size_t num_rx =
          rx_stream->recv(&host_buffer.front(), host_buffer.size(), md);

      if (num_rx > 0 && md.error_code == uhd::rx_metadata_t::ERROR_NONE) {
        // 1. DMA to GPU
        gpu_scanner->upload_samples(host_buffer.data());

        // 2. Execute Detection Kernel (Pass FPGA Timestamp base)
        uint64_t fpga_time_ns = md.time_spec.to_ticks(1.0e9);
        auto events = gpu_scanner->scan_for_beams(
            starlink::KU_CHANNELS[0].center_freq, fpga_time_ns);

        // 3. TDOA Telemetry Logic
        for (const auto &evt : events) {
          if (evt.is_vip_target) {
            // Create Lightweight Payload
            json payload;
            payload["node_id"] = node_id;
            payload["timestamp_ns"] = evt.timestamp_ns; // FPGA Precision
            payload["dwell_ms"] = evt.dwell_duration_ms;
            payload["freq_hz"] = starlink::KU_CHANNELS[0].center_freq;

            std::string msg = payload.dump();
            zmq::message_t zmq_msg(msg.data(), msg.size());
            zmq_pub.send(zmq_msg, zmq::send_flags::none);

            std::cout << "[TDOA] VIP Target | TS: " << evt.timestamp_ns
                      << " | Sent via ZMQ." << std::endl;
          }
        }
      }
    }
  }
};

int UHD_SAFE_MAIN(int argc, char *argv[]) {
  try {
    StarlinkHunter hunter;
    hunter.run_hunt();
  } catch (const std::exception &e) {
    std::cerr << "[FATAL] " << e.what() << std::endl;
    return 1;
  }
  return 0;
}
