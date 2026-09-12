# Local AI report highlights

Open **Report explanation** and select **Explain with local AI**. The runtime and model have been installed and verified on this development machine. On another installation, first select **Install local AI (5 GB)**. No Ollama service or separate terminal command is required.

The app owns its llama.cpp child process. It verifies the pinned archive and model checksums, extracts the runtime, selects the RX 7900 XTX when available, and starts an authenticated server bound to 127.0.0.1. Select **Use CPU instead of GPU** to run on CPU. Each request unloads the model afterward, releasing GPU memory. Cancel and closing the application terminate the owned process; a Linux parent-death signal also handles GUI process termination. Generation runs in a QThread, not the UI thread.

## What it does

Qwen3 8B chooses useful highlights from the calculated glucose report. It returns only known fact IDs; the app validates them and renders the existing verified wording and figures. Coverage and missing-time context are always retained. Arbitrary model-generated advice, new numeric claims and unknown IDs are rejected. This is constrained highlighting, not free-form medical chat, meal-causality analysis or insulin-setting recommendations.

The full calculated explanation remains available if the model fails or is not installed. Report refreshes invalidate previous highlights. Summary exports include accepted highlights, their evidence fingerprint and pinned model/runtime hashes so the output can be linked to the corresponding report.

## Assets and privacy

- Runtime: official llama.cpp b10900 Linux x64 Vulkan archive, 30,155,355 bytes, SHA256 `d6335e113bf901817be911e8b12f39faadb78e86a6ac22ac3eb0f9037f3c01de`.
- Model: official Qwen3-8B-Q4_K_M.gguf, revision `7c41481f57cb95916b40956ab2f0b139b296d974`, 5,027,783,488 bytes, SHA256 `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785`.
- Files reside in `$XDG_CACHE_HOME/bganalyzer/local-ai` (normally `~/.cache/bganalyzer/local-ai`). Config does not embed the model.
- Installation connects to official GitHub/Hugging Face downloads and their redirect hosts. Inference sends report facts only to the owned localhost server, with proxy environment use disabled and runtime offline mode enabled. Runtime stdout/stderr are discarded; report text is not logged.
- Download sizes and SHA256 hashes must match before installation succeeds. Cancellation removes the incomplete download; retry starts that file again. Existing verified files are reused.

The pinned b10900 runtime replaces the implementation plan's initial source revision for this development integration. Qwen3 8B replaces the proposed 14B model for the first tested highlights workflow. The executable is downloaded and managed by the app; a signed/packaged Flatpak distribution is still unfinished. CPU execution is supported by code but its performance has not been benchmarked here.

## Verification

A real synthetic inference on RX 7900 XTX completed in 6.8 seconds including verification, startup and cleanup. A separate real background-worker test checks the same path used by the UI. This is a synthetic functionality check, not a medical validation or a latency guarantee. Unit tests cover corrupt downloads, unknown/duplicate fact IDs, extra generated advice, loopback authorization, error cleanup, stale-report rejection and cancellation when closing the window.

Sources: [pinned llama.cpp release](https://github.com/ggml-org/llama.cpp/releases/tag/b10900), [official Qwen3 model repository](https://huggingface.co/Qwen/Qwen3-8B-GGUF/tree/7c41481f57cb95916b40956ab2f0b139b296d974).
