"""
providers/openai_tts_provider.py

OpenAI TTS Provider.
OpenAI Audio API를 사용하여 고품질 음성 합성을 수행한다.
스트리밍 응답을 청크 단위로 받아 즉시 재생하여 지연시간을 최소화한다.
"""

import io
import logging
import os
import queue
import threading
import wave
from argparse import Namespace

import numpy as np
import sounddevice as sd

from .base import TTSProvider
from ..audio_utils import MAX_TTS_ERRORS


class OpenAITTSProvider(TTSProvider):
    """OpenAI TTS API 기반 음성 합성 Provider.

    gpt-4o-mini-tts 모델을 사용하여 자연스러운 한국어 음성을 제공한다.
    WAV 포맷으로 응답을 받아 sounddevice로 재생한다.

    주요 특징:
        - gpt-4o-mini-tts 모델 (최신, 13개 음성)
        - 한국어 포함 다국어 지원
        - WAV 포맷 직접 재생 (별도 디코더 불필요)
        - 저렴한 비용 ($15/1M 글자)
    """

    def __init__(self, config: Namespace, interrupt_event: threading.Event) -> None:
        """OpenAI TTS Provider 초기화.

        Args:
            config: openai_tts_voice, openai_tts_model 등을 포함하는 설정 객체
            interrupt_event: 외부 인터럽트 이벤트

        Raises:
            ValueError: OPENAI_API_KEY가 설정되지 않은 경우
        """
        super().__init__(config, interrupt_event)

        self._queue: queue.Queue[str | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._is_speaking_event = threading.Event()
        self._has_failed = threading.Event()

        # API 키 확인
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY가 설정되지 않았습니다. "
                ".env 파일에 OPENAI_API_KEY를 설정해주세요."
            )

        # OpenAI 클라이언트 초기화
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=api_key)
        except ImportError:
            raise ImportError("openai 패키지가 설치되지 않았습니다: pip install openai")

        # 설정
        self._voice: str = getattr(config, "openai_tts_voice", "nova")
        self._model: str = getattr(config, "openai_tts_model", "gpt-4o-mini-tts")

        logging.info(
            f"OpenAI TTS 초기화 완료. 모델: {self._model}, 음성: {self._voice}"
        )

        # 워커 스레드 시작
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """OpenAI TTS API로 음성 합성.

        Args:
            text: 변환할 텍스트

        Returns:
            (int16 numpy 배열, 샘플레이트) 튜플

        Raises:
            RuntimeError: API 호출 실패 시
        """
        try:
            response = self._client.audio.speech.create(
                model=self._model,
                voice=self._voice,
                input=text,
                response_format="wav",
            )

            # WAV 바이너리를 numpy 배열로 변환
            audio_bytes = io.BytesIO(response.content)
            with wave.open(audio_bytes, "rb") as wf:
                sample_rate = wf.getframerate()
                n_frames = wf.getnframes()
                audio_data = wf.readframes(n_frames)
                n_channels = wf.getnchannels()

            audio_np = np.frombuffer(audio_data, dtype=np.int16)

            # 스테레오인 경우 모노로 변환
            if n_channels == 2:
                audio_np = audio_np.reshape(-1, 2).mean(axis=1).astype(np.int16)

            return audio_np, sample_rate

        except Exception as e:
            raise RuntimeError(f"OpenAI TTS API 오류: {e}") from e

    def _worker(self) -> None:
        """백그라운드 워커: 큐에서 텍스트를 가져와 API로 합성 후 재생."""
        consecutive_errors: int = 0

        while not self._stop_event.is_set():
            text: str | None = None
            try:
                text = self._queue.get(timeout=0.1)
                if text is None:
                    break

                self._is_speaking_event.set()

                # API로 음성 합성
                audio_int16, sample_rate = self._synthesize(text)

                # 인터럽트 확인
                if self.interrupt_event.is_set():
                    consecutive_errors = 0
                    continue

                # sounddevice로 오디오 재생
                output_device = getattr(
                    self.config, "piper_output_device_index", None
                )
                with sd.OutputStream(
                    samplerate=sample_rate,
                    device=output_device,
                    channels=1,
                    dtype="int16",
                ) as stream:
                    chunk_size: int = sample_rate // 10  # 100ms 단위
                    for i in range(0, len(audio_int16), chunk_size):
                        if self.interrupt_event.is_set():
                            break
                        chunk = audio_int16[i : i + chunk_size]
                        stream.write(chunk)

                consecutive_errors = 0

            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"OpenAI TTS 오류: {e}")
                consecutive_errors += 1
                if consecutive_errors >= MAX_TTS_ERRORS:
                    logging.critical(
                        f"OpenAI TTS 연속 {MAX_TTS_ERRORS}회 오류. "
                        f"TTS를 비활성화합니다."
                    )
                    self._has_failed.set()
                    break
            finally:
                if text is not None:
                    self._queue.task_done()
                if self._queue.empty():
                    self._is_speaking_event.clear()

    def speak(self, text: str) -> None:
        """텍스트를 음성으로 변환하여 재생 큐에 추가."""
        if not self._has_failed.is_set():
            self._queue.put(text)

    def stop(self) -> None:
        """음성 합성 중단 및 모든 리소스 정리."""
        self._stop_event.set()
        self.clear_queue()
        self._queue.put(None)
        self._thread.join(timeout=5.0)
        self._client = None

    def clear_queue(self) -> None:
        """대기 중인 음성 큐 초기화."""
        with self._queue.mutex:
            self._queue.queue.clear()

    def wait_until_done(self) -> None:
        """현재 큐의 모든 음성이 재생 완료될 때까지 대기."""
        self._queue.join()

    @property
    def is_speaking(self) -> bool:
        """현재 음성 출력 중 여부."""
        return self._is_speaking_event.is_set()

    @property
    def has_failed(self) -> bool:
        """치명적 오류 발생 여부."""
        return self._has_failed.is_set()
