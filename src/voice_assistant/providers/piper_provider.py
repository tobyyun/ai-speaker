"""
providers/piper_provider.py

Piper TTS Provider 래퍼.
기존 Synthesizer 로직을 TTSProvider ABC로 래핑하여
팩토리 패턴을 통해 사용할 수 있도록 한다.
"""

import logging
import threading
from argparse import Namespace

from .base import TTSProvider
from ..synthesizer import Synthesizer


class PiperProvider(TTSProvider):
    """Piper 기반 TTS Provider.

    기존 Synthesizer를 내부적으로 사용하여 ONNX 모델 기반 음성 합성을 수행한다.
    스레드 기반 워커와 큐를 활용한 비동기 재생을 지원한다.
    """

    def __init__(self, config: Namespace, interrupt_event: threading.Event) -> None:
        """Piper Provider 초기화.

        기존 Synthesizer를 내부적으로 생성한다.

        Args:
            config: piper_model_path, piper_output_device_index 등을 포함하는 설정 객체
            interrupt_event: 외부 인터럽트 이벤트 (음성 합성 중단용)

        Raises:
            FileNotFoundError: 모델 파일을 찾을 수 없는 경우
            RuntimeError: Piper 모델 로딩 실패 시
        """
        super().__init__(config, interrupt_event)
        logging.info("PiperProvider 초기화 중...")

        # 기존 Synthesizer를 컴포지션으로 활용
        self._synthesizer = Synthesizer(config, interrupt_event)

        # Synthesizer 초기화 후 치명적 오류 확인
        if self._synthesizer.has_failed.is_set():
            raise RuntimeError("Piper TTS 모델 초기화에 실패했습니다.")

        logging.info("PiperProvider 초기화 완료.")

    def speak(self, text: str) -> None:
        """텍스트를 음성으로 변환하여 재생 큐에 추가.

        Args:
            text: 음성으로 변환할 텍스트
        """
        self._synthesizer.speak(text)

    def stop(self) -> None:
        """음성 합성 중단 및 모든 리소스 정리."""
        self._synthesizer.stop()

    def clear_queue(self) -> None:
        """대기 중인 음성 큐 초기화."""
        self._synthesizer.clear_queue()

    def wait_until_done(self) -> None:
        """현재 큐의 모든 음성이 재생 완료될 때까지 대기."""
        self._synthesizer.queue.join()

    @property
    def is_speaking(self) -> bool:
        """현재 음성 출력 중 여부."""
        return self._synthesizer.is_speaking_event.is_set()

    @property
    def has_failed(self) -> bool:
        """치명적 오류 발생 여부."""
        return self._synthesizer.has_failed.is_set()
