"""
providers 패키지

AI Provider 추상화 레이어.
LLM, TTS, STT Provider를 위한 ABC, 팩토리, 레거시 래퍼를 제공한다.
의존성이 설치되지 않은 Provider는 건너뛰고 경고를 출력한다.
"""

import logging

from .base import LLMProvider, STTProvider, TTSProvider
from .factory import ProviderFactory

# 레거시 Provider를 조건부로 등록 (의존성 미설치 시 건너뜀)
try:
    from .ollama_provider import OllamaProvider
    ProviderFactory.register_llm("ollama", OllamaProvider)
except ImportError as e:
    logging.debug(f"OllamaProvider 등록 건너뜀 (의존성 미설치): {e}")

try:
    from .piper_provider import PiperProvider
    ProviderFactory.register_tts("piper", PiperProvider)
except ImportError as e:
    logging.debug(f"PiperProvider 등록 건너뜀 (의존성 미설치): {e}")

try:
    from .whisper_provider import WhisperProvider
    ProviderFactory.register_stt("whisper", WhisperProvider)
except ImportError as e:
    logging.debug(f"WhisperProvider 등록 건너뜀 (의존성 미설치): {e}")

# Claude LLM Provider 조건부 등록
try:
    from .claude_provider import ClaudeProvider
    ProviderFactory.register_llm("claude", ClaudeProvider)
except ImportError as e:
    logging.debug(f"ClaudeProvider 등록 건너뜀 (의존성 미설치): {e}")

# Supertonic TTS Provider 조건부 등록
try:
    from .supertonic_provider import SupertonicProvider
    ProviderFactory.register_tts("supertonic", SupertonicProvider)
except ImportError as e:
    logging.debug(f"SupertonicProvider 등록 건너뜀 (의존성 미설치): {e}")

# Grok TTS Provider 등록 (WebSocket 스트리밍)
try:
    from .grok_tts_provider import GrokTTSProvider
    ProviderFactory.register_tts("grok", GrokTTSProvider)
except ImportError as e:
    logging.debug(f"GrokTTSProvider 등록 건너뜀 (의존성 미설치): {e}")

# OpenAI TTS Provider 등록
try:
    from .openai_tts_provider import OpenAITTSProvider
    ProviderFactory.register_tts("openai", OpenAITTSProvider)
except ImportError as e:
    logging.debug(f"OpenAITTSProvider 등록 건너뜀 (의존성 미설치): {e}")

# Supertone Play API TTS Provider 등록
try:
    from .supertone_play_provider import SupertonePlayProvider
    ProviderFactory.register_tts("supertone_play", SupertonePlayProvider)
except ImportError as e:
    logging.debug(f"SupertonePlayProvider 등록 건너뜀 (의존성 미설치): {e}")

__all__ = [
    "LLMProvider",
    "TTSProvider",
    "STTProvider",
    "ProviderFactory",
]
