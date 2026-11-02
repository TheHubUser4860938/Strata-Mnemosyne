// bench/p1/tensor_rate.cu - is the Ada unlock live on this card, measured, not inferred?
//
// The owner's question of 2026-10-30: "Prefill is now cut in half - did the unlock fail on the GPU?"  The
// gpu-unlock-ada README prices the effect as ~2x FP16 and BF16 tensor throughput WITH FP32 ACCUMULATION
// (165.6 -> 331.6 TF/s FP16, 165.5 -> 330.6 TF/s BF16 on an RTX 4090, driver 615.78.08; an independent
// matched run of revision 8855e7b measured 160.4 -> 320.4 TF/s).  Stock rates are therefore ~165 and
// unlocked rates ~330, and nothing in Strata's own logs says which one it is running at - so this program
// asks the card directly: one cuBLAS GEMM per dtype, FP32 accumulate, F32 out, timed over repeats.
//
// Read the numbers as a floor, not a ceiling: the card is shared with the serving engine, so a run taken
// while a conversation is in flight sees contention.  The two dtypes are measured back to back in the same
// process, so FP16-vs-BF16 is a same-moment comparison; only the 165/330 verdict needs a quiet card.
//
// build: nvcc -O3 -lcublas tensor_rate.cu -o tensor_rate   run: ./tensor_rate [N]
#include <cublas_v2.h>
#include <algorithm>
#include <dlfcn.h>
#include <cuda_fp16.h>
#include <cuda_bf16.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#define CU(x) do { cudaError_t e = (x); if (e != cudaSuccess) { std::fprintf(stderr, "cuda: %s\n", cudaGetErrorString(e)); std::exit(1); } } while (0)
#define CB(x) do { cublasStatus_t s = (x); if (s != CUBLAS_STATUS_SUCCESS) { std::fprintf(stderr, "cublas: %d\n", (int) s); std::exit(1); } } while (0)

namespace {
double now_ms() { timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts); return ts.tv_sec * 1e3 + ts.tv_nsec / 1e6; }

// The clock the card is ACTUALLY at while the GEMM runs.  Ten 4096^3 reps finish in ~12 ms, which is inside the
// idle-to-boost ramp (the owner's own 2026-10-30 note: the app was "locked in idle" until whitelisted), so a
// short window reads 99-137 TF/s on a card whose rate table reaches 331.  Sampling SM clock during the burn
// separates "the unlock is off" from "the burn never got to boost".
struct ClockSampler {
    void* nvml = nullptr;
    void* dev = nullptr;                                        // nvmlDevice_t is a HANDLE, not an index
    int (*init)(void) = nullptr;
    int (*by_index)(unsigned idx, void** h) = nullptr;
    int (*get_clock)(void* h, int type, unsigned* mhz) = nullptr;
    std::vector<unsigned> seen;
    bool ok = false;
    ClockSampler() {
        nvml = dlopen("libnvidia-ml.so.1", RTLD_NOW);
        if (!nvml) return;
        *reinterpret_cast<void**>(&init) = dlsym(nvml, "nvmlInit_v2");
        *reinterpret_cast<void**>(&by_index) = dlsym(nvml, "nvmlDeviceGetHandleByIndex_v2");
        *reinterpret_cast<void**>(&get_clock) = dlsym(nvml, "nvmlDeviceGetClockInfo");
        if (!init || !by_index || !get_clock) return;
        // The first run's sampler reported 0 MHz because it passed 0 as a device INDEX; nvmlDevice_t is a
        // pointer, so that was a null handle and every sample failed silently.  Get a real handle.
        if (init() == 0 && by_index(0, &dev) == 0 && dev) ok = true;
    }
    unsigned sample() {
        unsigned mhz = 0;
        if (ok && get_clock(dev, 1 /*NVML_CLOCK_SM*/, &mhz) == 0) { seen.push_back(mhz); return mhz; }
        return 0;
    }
    unsigned median() {
        if (seen.empty()) return 0;
        std::sort(seen.begin(), seen.end());
        return seen[seen.size() / 2];
    }
};
ClockSampler g_clk;

template <typename T>
double rate(cublasHandle_t h, cudaDataType_t dt, int n, double seconds) {
    const size_t elems = (size_t) n * n;
    T *A = nullptr, *B = nullptr; float *C = nullptr;
    CU(cudaMalloc(&A, elems * sizeof(T))); CU(cudaMalloc(&B, elems * sizeof(T))); CU(cudaMalloc(&C, elems * sizeof(float)));
    std::vector<T> host(elems);
    for (size_t i = 0; i < elems; ++i) host[i] = T((float)((i % 97) - 48) / 97.0f);
    CU(cudaMemcpy(A, host.data(), elems * sizeof(T), cudaMemcpyHostToDevice));
    CU(cudaMemcpy(B, host.data(), elems * sizeof(T), cudaMemcpyHostToDevice));
    const float one = 1.0f, zero = 0.0f;
    // row-major C = A * B is column-major C^T = B^T * A^T, which is what the plain op-N call below computes
    auto gemm = [&] {
        CB(cublasGemmEx(h, CUBLAS_OP_N, CUBLAS_OP_N, n, n, n, &one, B, dt, n, A, dt, n, &zero, C, CUDA_R_32F, n,
                        CUBLAS_COMPUTE_32F, CUBLAS_GEMM_DEFAULT));
    };
    // Calibrate: time one rep, then burn long enough (~`seconds`) that the clocks reach their sustained value
    // and stay there for the measurement.  This is the fix for the ramp-limited first readings.
    gemm();
    CU(cudaDeviceSynchronize());
    const double c0 = now_ms();
    gemm();
    CU(cudaDeviceSynchronize());
    const double one_ms = (now_ms() - c0) / 1000.0;
    int reps = (int) (seconds / (one_ms > 1e-6 ? one_ms : 1e-6));
    if (reps < 10) reps = 10;
    for (int i = 0; i < 5; ++i) gemm();          // warm the kernels and start the ramp
    CU(cudaDeviceSynchronize());
    const double t0 = now_ms();
    for (int i = 0; i < reps; ++i) { gemm(); if ((i & 15) == 0) g_clk.sample(); }
    CU(cudaDeviceSynchronize());
    const double ms = now_ms() - t0;
    const unsigned mhz = g_clk.median();
    cudaFree(A); cudaFree(B); cudaFree(C);
    std::printf("      %3d reps, %5.0f ms, SM clock median %u MHz\n", reps, ms, mhz);
    return 2.0 * (double) n * n * n * reps / (ms * 1e9);   // TF/s
}
}  // namespace

int main(int argc, char** argv) {
    const int n = argc > 1 ? std::atoi(argv[1]) : 4096;
    const double secs = argc > 2 ? std::atof(argv[2]) : 1.5;   // the burn length, not a rep count
    int dev = 0; cudaGetDevice(&dev);
    size_t free_b = 0, total_b = 0;
    CU(cudaMemGetInfo(&free_b, &total_b));
    std::printf("  (device memory: %.0f MiB free of %.0f MiB - a cublas handle needs a workspace from this)\n",
                free_b / 1048576.0, total_b / 1048576.0);
    cublasHandle_t h; CB(cublasCreate(&h));
    cudaDeviceProp p; cudaGetDeviceProperties(&p, dev);
    std::printf("tensor_rate: %s (%d SMs, cc %d.%d), cublas GEMM N=%d, FP32 accumulate, F32 out, ~%.1f s burn per shape\n",
                p.name, p.multiProcessorCount, p.major, p.minor, n, secs);
    std::printf("  FP16 -> FP32 : %6.1f TF/s   (stock ~165.6, unlocked ~331.6 per the gpu-unlock-ada table)\n",
                rate<__half>(h, CUDA_R_16F, n, secs));
    std::printf("  BF16 -> FP32 : %6.1f TF/s   (stock ~165.5, unlocked ~330.6)\n",
                rate<__nv_bfloat16>(h, CUDA_R_16BF, n, secs));
    cublasDestroy(h);
    return 0;
}
