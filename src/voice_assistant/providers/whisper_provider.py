"""
providers/whisper_provider.py

faster-whisper STT Provider 래퍼.
기존 Transcriber 로직을 STTProvider ABC로 래핑하여
팩토리 패턴을 통해 사용할 수 있도록 한다.
"""

import logging
from argparse import Namespace

import numpy as np
import numpy.typing as npt

from .base import STTProvider
from ..transcriber import Transcriber


class WhisperProvider(STTProvider):
    """faster-whisper 기반 STT Provider.

    기존 Transcriber를 내부적으로 사용하여 로컬 Whisper 모델 기반 음성 인식을 수행한다.
    타임아웃 및 재시도 로직이 포함되어 있다.
    """

    def __init__(self, config: Namespace) -> None:
        """Whisper Provider 초기화.

        기존 Transcriber를 내부적으로 생성한다.

        Args:
            config: whisper_model, whisper_device, whisper_compute_type 등을 포함하는 설정 객체

        Raises:
            RuntimeError: Whisper 모델 로딩 실패 시
        """
        super().__init__(config)
        logging.info("WhisperProvider 초기화 중...")

        try:
            # 기존 Transcriber를 컴포지션으로 활용
            self._transcriber = Transcriber(config)
            logging.info("WhisperProvider 초기화 완료.")
        except Exception as e:
            logging.error(f"Whisper 모델 로딩 실패: {e}")
            raise RuntimeError(f"Whisper STT 모델 초기화에 실패했습니다: {e}") from e

    def transcribe(self, audio_np: npt.NDArray[np.float32]) -> str:
        """오디오 numpy 배열을 텍스트로 변환.

        Args:
            audio_np: float32 형식의 오디오 numpy 배열 (16kHz)

        Returns:
            인식된 텍스트 문자열. 인식 실패 시 빈 문자열.
        """
        return self._transcriber.transcribe(audio_np)

    def close(self) -> None:
        """모델 리소스 정리."""
        logging.debug("WhisperProvider 리소스 정리 중")
        self._transcriber.close()
