#include "../include/starlink_defs.hpp"
#include <complex>
#include <cuda_runtime.h>
#include <cufft.h>
#include <thrust/device_vector.h>
#include <thrust/extrema.h>
#include <vector>


// CUDA KERNEL: POWER DETECTOR & BURST TRIGGER
// Inputs: Raw IQ samples (complex64)
// Output: Burst Markers (Start/End indices)

__global__ void compute_power_kernel(const float2 *__restrict__ iq_data,
                                     float *__restrict__ power_out,
                                     int num_samples) {
  int idx = blockIdx.x * blockDim.x + threadIdx.x;
  if (idx < num_samples) {
    float i = iq_data[idx].x;
    float q = iq_data[idx].y;
    // Calcolo potenza istantanea
    power_out[idx] = (i * i) + (q * q);
  }
}

// Host Wrapper class
class CudaBeamScanner {
  float2 *d_iq_input;
  float *d_power;
  int batch_size;
  cufftHandle fft_plan;

public:
  CudaBeamScanner(int size) : batch_size(size) {
    cudaMalloc(&d_iq_input, size * sizeof(float2));
    cudaMalloc(&d_power, size * sizeof(float));
  }

  ~CudaBeamScanner() {
    cudaFree(d_iq_input);
    cudaFree(d_power);
  }

  // Carica dati raw dalla RAM principale alla GPU
  void upload_samples(const std::complex<float> *host_data) {
    cudaMemcpy(d_iq_input, host_data, batch_size * sizeof(float2),
               cudaMemcpyHostToDevice);
  }

  // Analizza il flusso per trovare "Beam Dwells"
  std::vector<starlink::BeamEvent> scan_for_beams(double center_freq,
                                                  uint64_t start_time_ns) {
    int threads = 256;
    int blocks = (batch_size + threads - 1) / threads;

    // 1. Calcola potenza su GPU
    compute_power_kernel<<<blocks, threads>>>(d_iq_input, d_power, batch_size);

    // 2. Scarica potenza su Host per analisi logica (o usa Thrust su device per
    // reduction) Per latenza bassissima, meglio analizzare su CPU i risultati
    // ridotti, ma qui scarichiamo il buffer potenza per semplicità di debug.
    std::vector<float> host_power(batch_size);
    cudaMemcpy(host_power.data(), d_power, batch_size * sizeof(float),
               cudaMemcpyDeviceToHost);

    std::vector<starlink::BeamEvent> events;
    bool in_burst = false;
    uint64_t burst_start_idx = 0;
    float noise_floor = 0.001f;            // Da calcolare dinamicamente
    float threshold = noise_floor * 10.0f; // 10dB sopra rumore

    // LOGICA DI RILEVAMENTO BURST (Time Domain)
    for (int i = 0; i < batch_size; i++) {
      if (!in_burst && host_power[i] > threshold) {
        in_burst = true;
        burst_start_idx = i;
      } else if (in_burst && host_power[i] < threshold) {
        // Fine del burst
        in_burst = false;
        uint64_t duration_samples = i - burst_start_idx;
        double sample_rate = 250e6; // 250 Msps assumption
        double duration_ms = (double)duration_samples / sample_rate * 1000.0;

        if (duration_ms > 0.05) { // Filtra glitch < 50us
          starlink::BeamEvent evt;
          evt.timestamp_ns =
              start_time_ns +
              (uint64_t)((double)burst_start_idx / sample_rate * 1e9);
          evt.dwell_duration_ms = duration_ms;
          evt.power_dbm = 10 * log10(host_power[burst_start_idx]); // Peak

          // SE IL BURST DURA TROPPO, È UN TARGET "VIP"
          evt.is_vip_target = (duration_ms > starlink::VIP_DWELL_TIME_MS);

          events.push_back(evt);
        }
      }
    }
    return events;
  }
};
