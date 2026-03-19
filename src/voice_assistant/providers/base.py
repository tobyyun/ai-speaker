"""
providers/base.py

LLM, TTS, STT Provider 추상 베이스 클래스(ABC) 정의.
모든 Provider는 이 ABC를 상속하여 일관된 인터페이스를 제공해야 한다.
"""

import threading
from abc import ABC, abstractmethod
from argparse import Namespace
from typing import Generator

import numpy as np
import numpy.typing as npt


class LLMProvider(ABC):
    """LLM(대규모 언어 모델) Provider 추상 베이스 클래스.

    모든 LLM Provider는 이 클래스를 상속하고
    chat_stream, reset_history, close 메서드를 구현해야 한다.
    """

    def __init__(self, config: Namespace) -> None:
        """Provider 초기화.

        Args:
            config: argparse.Namespace 설정 객체
        """
        self.config = config
        self.system_prompt: str = getattr(config, "system_prompt", "")
        self.max_history_messages: int = getattr(config, "max_history_tokens", 2048)

    @abstractmethod
    def chat_stream(self, user_text: str) -> Generator[str | None, None, None]:
        """사용자 입력에 대한 LLM 응답을 토큰 단위로 스트리밍.

        Args:
            user_text: 사용자 입력 텍스트

        Yields:
            str | None: 응답 토큰 문자열, 오류 시 None
        """
        ...

    @abstractmethod
    def reset_history(self) -> None:
        """대화 히스토리를 시스템 프롬프트만 남기고 초기화."""
        ...

    @abstractmethod
    def close(self) -> None:
        """리소스 정리 및 연결 해제."""
        ...


class TTSProvider(ABC):
    """TTS(텍스트 음성 변환) Provider 추상 베이스 클래스.

    모든 TTS Provider는 이 클래스를 상속하고
    speak, stop, clear_queue, wait_until_done 메서드를 구현해야 한다.
    """

    def __init__(self, config: Namespace, interrupt_event: threading.Event) -> None:
        """Provider 초기화.

        Args:
            config: argparse.Namespace 설정 객체
            interrupt_event: 외부 인터럽트 이벤트 (음성 합성 중단용)
        """
        self.config = config
        self.interrupt_event = interrupt_event

    @abstractmethod
    def speak(self, text: str) -> None:
        """텍스트를 음성으로 변환하여 재생 큐에 추가.

        Args:
            text: 음성으로 변환할 텍스트
        """
        ...

    @abstractmethod
    def stop(self) -> None:
        """음성 합성 중단 및 모든 리소스 정리."""
        ...

    @abstractmethod
    def clear_queue(self) -> None:
        """대기 중인 음성 큐 초기화."""
        ...

    @abstractmethod
    def wait_until_done(self) -> None:
        """현재 큐의 모든 음성이 재생 완료될 때까지 대기."""
        ...

    @property
    @abstractmethod
    def is_speaking(self) -> bool:
        """현재 음성 출력 중 여부."""
        ...

    @property
    @abstractmethod
    def has_failed(self) -> bool:
        """치명적 오류 발생 여부."""
        ...


class STTProvider(ABC):
    """STT(음성 텍스트 변환) Provider 추상 베이스 클래스.

    모든 STT Provider는 이 클래스를 상속하고
    transcribe, close 메서드를 구현해야 한다.
    """

    def __init__(self, config: Namespace) -> None:
        """Provider 초기화.

        Args:
            config: argparse.Namespace 설정 객체
        """
        self.config = config
        self.language: str = getattr(config, "default_language", "ko")

    @abstractmethod
    def transcribe(self, audio_np: npt.NDArray[np.float32]) -> str:
        """오디오 numpy 배열을 텍스트로 변환.

        Args:
            audio_np: float32 형식의 오디오 numpy 배열 (16kHz)

        Returns:
            인식된 텍스트 문자열. 인식 실패 시 빈 문자열.
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """모델 리소스 정리."""
        ...
