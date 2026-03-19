"""
providers/supertonic_provider.py

Supertonic TTS Provider.
Supertonic ONNX 모델을 사용하여 한국어 음성 합성을 수행한다.
기존 Synthesizer의 큐 기반 비동기 재생 패턴을 따른다.
"""

import logging
import queue
import threading
from argparse import Namespace

import numpy as np
import sounddevice as sd
from scipy.signal import resample

from .base import TTSProvider
from ..audio_utils import MAX_TTS_ERRORS


class SupertonicProvider(TTSProvider):
    """Supertonic 기반 TTS Provider.

    Supertonic ONNX 모델을 사용하여 한국어 텍스트를 음성으로 변환한다.
    백그라운드 워커 스레드에서 큐 기반으로 순차 재생하며,
    sounddevice.OutputStream을 통해 오디오를 출력한다.

    주요 특징:
        - TTS(auto_download=True)로 모델 자동 다운로드
        - 한국어 여성 음성 (F3) 기본 사용
        - 24kHz 출력을 48kHz로 리샘플링하여 sounddevice 호환
        - interrupt_event를 통한 재생 중단 지원
    """

    def __init__(self, config: Namespace, interrupt_event: threading.Event) -> None:
        """Supertonic Provider 초기화.

        TTS 엔진을 로드하고 음성 스타일을 설정한 후 워커 스레드를 시작한다.

        Args:
            config: supertonic_voice, piper_output_device_index 등을 포함하는 설정 객체
            interrupt_event: 외부 인터럽트 이벤트 (음성 합성 중단용)

        Raises:
            RuntimeError: Supertonic 모델 초기화 실패 시
        """
        super().__init__(config, interrupt_event)

        self._queue: queue.Queue[str | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._is_speaking_event = threading.Event()
        self._has_failed = threading.Event()

        # Supertonic TTS 엔진 초기화
        self._tts = None
        self._voice = None
        self._sample_rate: int = 24000  # Supertonic 기본 출력 샘플레이트
        self._lang: str = getattr(config, "default_language", "ko")

        self._load_model()

        # 워커 스레드 시작
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _load_model(self) -> None:
        """Supertonic TTS 모델 및 음성 스타일 로드.

        auto_download=True로 설정하여 모델이 없으면 자동 다운로드한다.
        """
        logging.info("Supertonic TTS 초기화 중...")
        try:
            from supertonic import TTS

            self._tts = TTS(auto_download=True)

            # 샘플레이트를 TTS 엔진에서 가져오기 (가능한 경우)
            if hasattr(self._tts, "sample_rate"):
                self._sample_rate = self._tts.sample_rate

            # 음성 스타일 설정 (config에서 설정 가능, 기본값 F3)
            voice_name: str = getattr(self.config, "supertonic_voice", "F3")
            self._voice = self._tts.get_voice_style(voice_name)

            logging.info(
                f"Supertonic TTS 초기화 완료. "
                f"음성: {voice_name}, 샘플레이트: {self._sample_rate}Hz, "
                f"언어: {self._lang}"
            )
        except Exception as e:
            logging.critical(f"Supertonic TTS 초기화 실패: {e}")
            self._has_failed.set()

    def _worker(self) -> None:
        """백그라운드 워커: 큐에서 텍스트를 가져와 음성 합성 후 재생.

        기존 Synthesizer._worker 패턴을 따른다.
        - queue.Queue에서 텍스트를 대기
        - supertonic.synthesize()로 음성 합성
        - sounddevice.OutputStream으로 재생
        - interrupt_event 감지 시 재생 중단
        - 연속 오류 카운터로 치명적 오류 판별
        """
        consecutive_errors: int = 0
        target_sample_rate: int = 48000  # 디바이스 기본 샘플레이트

        while not self._stop_event.is_set():
            text: str | None = None
            try:
                text = self._queue.get(timeout=0.1)
                if text is None:
                    break

                self._is_speaking_event.set()

                # Supertonic으로 음성 합성
                # 반환값: (wav: np.ndarray shape=(1, num_samples), duration: np.ndarray)
                wav, _duration = self._tts.synthesize(
                    text,
                    voice_style=self._voice,
                    lang=self._lang,
                )

                # (1, num_samples) -> (num_samples,) 형태로 변환
                audio_float = wav.squeeze()

                # float32 [-1.0, 1.0] -> int16 [-32768, 32767] 변환
                audio_int16 = (audio_float * 32767).astype(np.int16)

                # 리샘플링 (24kHz -> 48kHz)
                if self._sample_rate != target_sample_rate:
                    num_samples = round(
                        len(audio_int16) * target_sample_rate / self._sample_rate
                    )
                    audio_int16 = resample(audio_int16, num_samples).astype(np.int16)

                # 인터럽트 확인
                if self.interrupt_event.is_set():
                    consecutive_errors = 0
                    continue

                # sounddevice로 오디오 재생
                output_device = getattr(
                    self.config, "piper_output_device_index", None
                )
                with sd.OutputStream(
                    samplerate=target_sample_rate,
                    device=output_device,
                    channels=1,
                    dtype="int16",
                ) as stream:
                    # 청크 단위로 재생 (인터럽트 대응)
                    chunk_size: int = target_sample_rate // 10  # 100ms 단위
                    for i in range(0, len(audio_int16), chunk_size):
                        if self.interrupt_event.is_set():
                            break
                        chunk = audio_int16[i : i + chunk_size]
                        stream.write(chunk)

                consecutive_errors = 0

            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"Supertonic TTS 오류: {e}")
                consecutive_errors += 1
                if consecutive_errors >= MAX_TTS_ERRORS:
                    logging.critical(
                        f"Supertonic TTS 연속 {MAX_TTS_ERRORS}회 오류 발생. "
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
        """텍스트를 음성으로 변환하여 재생 큐에 추가.

        Args:
            text: 음성으로 변환할 텍스트
        """
        if not self._has_failed.is_set():
            self._queue.put(text)

    def stop(self) -> None:
        """음성 합성 중단 및 모든 리소스 정리."""
        self._stop_event.set()
        self.clear_queue()
        self._queue.put(None)  # 센티널 값으로 워커 종료
        self._thread.join(timeout=5.0)

        # TTS 모델 리소스 정리
        if self._tts is not None:
            del self._tts
            self._tts = None
        if self._voice is not None:
            del self._voice
            self._voice = None

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
