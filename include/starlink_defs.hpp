#pragma once
#include <cstdint>
#include <array>
#include <vector>

namespace starlink {

    // KNOWLEDGE BASE: KU-BAND DOWNLINK PLAN
    // Based on observational data, not public specs.
    struct ChannelConfig {
        double center_freq;
        double bandwidth;
        int channel_id;
    };

    // I canali principali osservati (Shell 1 & 4)
    const std::vector<ChannelConfig> KU_CHANNELS = {
        {11.325e9, 240e6, 1}, // Channel 1: 11.325 GHz (Primary Beacon/Control)
        {11.575e9, 240e6, 2}, // Channel 2: 11.575 GHz
        {10.975e9, 240e6, 3}, // Channel 3: Lower Ku
        {12.225e9, 240e6, 4}  // Channel 4: Upper Ku
    };

    // OFDM PARAMETERS (Estimated)
    constexpr double SYMBOL_TIME_US = 14.44; // Microseconds (approx)
    constexpr int SUBCARRIERS = 1024;        // Likely FFT size per sub-channel
    
    // BEAM HOPPING THRESHOLDS
    constexpr double MIN_DWELL_TIME_MS = 1.0; 
    constexpr double VIP_DWELL_TIME_MS = 10.0; // If beam holds >10ms, it's high traffic

    struct BeamEvent {
        uint64_t timestamp_ns;
        int channel_id;
        double power_dbm;
        double dwell_duration_ms;
        double doppler_shift_hz;
        bool is_vip_target; // Flag for anomalous dwell time
    };
}
