#!/usr/bin/env python3

"""
assistant.py

The main entry point for the hands-free Python voice assistant.
Loads configuration, initializes, and runs the VoiceAssistant class.
"""

import logging
import sys
import tracemalloc
import warnings

# Suppress the specific onnxruntime UserWarning
warnings.filterwarnings("ignore", message="Specified provider 'CUDAExecutionProvider' is not in available provider names.")
# Suppress the pkg_resources deprecation warning from webrtcvad
warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API")


# --- IMPROVEMENT: Top-Level Dependency Check ---
# Encapsulate critical imports to provide clear error messages if dependencies are missing.
try:
    from .config_manager import load_config_and_args
    from .voice_assistant import VoiceAssistant
except ImportError as e:
    print(
        f"FATAL: Missing required Python module: {e.name}. Please ensure all dependencies are installed (e.g., via pip install -r requirements.txt).",
        file=sys.stderr,
    )
    sys.exit(1)
# --- END IMPROVEMENT ---


def setup_logging():
    """Configures the logging format and level."""
    log_format = "%(levelname)s %(asctime)s - %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main() -> None:
    """The entry point for the assistant application."""

    # Initialize logging first to catch all subsequent errors
    try:
        setup_logging()
    except Exception as e:
        # A simple print if setup_logging fails entirely
        print(f"FATAL: Could not set up logging: {e}", file=sys.stderr)
        sys.exit(1)

    args, _, should_exit = load_config_and_args()

    # --- 주요 설정 로깅 ---
    logging.info(f"LLM Provider: {args.llm_provider}")
    logging.info(f"TTS Provider: {args.tts_provider}")
    logging.info(f"STT Provider: {args.stt_provider}")
    logging.info(f"Trim wake word from transcription: {'Enabled' if args.trim_wake_word else 'Disabled'}")
    # ---

    # 상세 메모리 트레이싱 (디버그 모드)
    if args.debug:
        tracemalloc.start()

    assistant: VoiceAssistant | None = None
    try:
        # 장치 목록 출력 후 종료 플래그 처리
        if should_exit:
            sys.exit(0)

        assistant = VoiceAssistant(args)

        assistant.run()

    except IOError as e:
        # This catches PyAudio/sounddevice stream errors during initialization
        logging.critical(f"FATAL ERROR during audio initialization: {e}")
        logging.critical("Check microphone connectivity or use --list-devices.")
    except (RuntimeError, OSError, ValueError) as e:
        # This catches model loading errors (Whisper, Piper, OpenWakeWord)
        logging.critical(f"FATAL ERROR during model loading: {e}")
    except Exception as e:
        logging.critical(f"An unexpected error occurred: {e}", exc_info=True)
    finally:
        # Ensure cleanup runs even if initialization failed
        if assistant:
            assistant.cleanup()
        
        # Log memory usage if enabled
        if args.debug and tracemalloc.is_tracing():
            snapshot = tracemalloc.take_snapshot()
            top_stats = snapshot.statistics('lineno')
            logging.debug("--- Top 10 Memory Allocations ---")
            for stat in top_stats[:10]:
                logging.debug(stat)
            logging.debug("---------------------------------")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        # This allows --list-devices and --list-output-devices to exit cleanly
        pass
