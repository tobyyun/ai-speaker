"""
providers/supertone_play_provider.py

Supertone Play API TTS Provider.
Supertone Play 클라우드 API를 사용하여 고품질 한국어 음성 합성을 수행한다.
기존 Synthesizer의 큐 기반 비동기 재생 패턴을 따른다.
"""

import io
import logging
import os
import queue
import threading
import wave
from argparse import Namespace

import numpy as np
import requests
import sounddevice as sd

from .base import TTSProvider
from ..audio_utils import MAX_TTS_ERRORS

# Supertone Play API 기본 설정
SUPERTONE_API_BASE = "https://supertoneapi.com"
DEFAULT_MODEL = "sona_speech_2_flash"
MAX_TEXT_LENGTH = 300


class SupertonePlayProvider(TTSProvider):
    """Supertone Play API 기반 TTS Provider.

    Supertone Play 클라우드 API를 사용하여 고품질 음성 합성을 수행한다.
    sona_speech_2_flash 모델로 자연스러운 한국어 음성을 제공한다.

    주요 특징:
        - 클라우드 API 기반 고품질 음성 합성
        - sona_speech_2_flash 모델 (최신, 고속)
        - 150+ 프리셋 음성 지원
        - 감정/스타일 조절 가능
        - interrupt_event를 통한 재생 중단 지원
    """

    def __init__(self, config: Namespace, interrupt_event: threading.Event) -> None:
        """Supertone Play Provider 초기화.

        API 키를 검증하고 워커 스레드를 시작한다.

        Args:
            config: supertone_voice_id, default_language 등을 포함하는 설정 객체
            interrupt_event: 외부 인터럽트 이벤트 (음성 합성 중단용)

        Raises:
            ValueError: SUPERTONE_API_KEY가 설정되지 않은 경우
        """
        super().__init__(config, interrupt_event)

        self._queue: queue.Queue[str | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._is_speaking_event = threading.Event()
        self._has_failed = threading.Event()

        # API 키 확인
        self._api_key = os.environ.get("SUPERTONE_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "SUPERTONE_API_KEY가 설정되지 않았습니다. "
                ".env 파일에 SUPERTONE_API_KEY를 설정해주세요. "
                "API 키는 https://play.supertone.ai 에서 발급받을 수 있습니다."
            )

        # 설정
        self._voice_id: str = getattr(config, "supertone_voice_id", "")
        self._model: str = getattr(config, "supertone_model", DEFAULT_MODEL)
        self._lang: str = getattr(config, "default_language", "ko")
        self._style: str = getattr(config, "supertone_style", "neutral")

        if not self._voice_id:
            raise ValueError(
                "supertone_voice_id가 설정되지 않았습니다. "
                "config.ini에 supertone_voice_id를 설정해주세요. "
                "음성 ID는 https://play.supertone.ai 의 Voice Library에서 확인할 수 있습니다."
            )

        # API 연결 테스트 (음성 정보 조회)
        self._verify_connection()

        logging.info(
            f"SupertonePlay TTS 초기화 완료. "
            f"음성: {self._voice_id}, 모델: {self._model}, 언어: {self._lang}"
        )

        # 워커 스레드 시작
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _verify_connection(self) -> None:
        """API 연결 테스트. predict-duration 엔드포인트로 검증 (크레딧 소모 없음)."""
        try:
            resp = requests.post(
                f"{SUPERTONE_API_BASE}/v1/predict-duration/{self._voice_id}",
                headers={
                    "x-sup-api-key": self._api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "text": "테스트",
                    "language": self._lang,
                    "model": self._model,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                logging.info("Supertone Play API 연결 확인 완료.")
            elif resp.status_code == 401:
                raise ValueError("Supertone API 키가 유효하지 않습니다.")
            elif resp.status_code == 404:
                raise ValueError(
                    f"음성 ID '{self._voice_id}'를 찾을 수 없습니다. "
                    f"올바른 voice_id를 확인해주세요."
                )
            else:
                logging.warning(
                    f"Supertone Play API 연결 테스트 응답: {resp.status_code} - {resp.text}"
                )
        except requests.ConnectionError as e:
            raise ConnectionError(
                f"Supertone Play API 서버에 연결할 수 없습니다: {e}"
            ) from e

    def _synthesize_api(self, text: str) -> np.ndarray:
        """Supertone Play API로 텍스트를 음성으로 변환.

        Args:
            text: 변환할 텍스트 (최대 300자)

        Returns:
            int16 numpy 배열의 오디오 데이터

        Raises:
            RuntimeError: API 호출 실패 시
        """
        # 300자 제한 처리
        if len(text) > MAX_TEXT_LENGTH:
            text = text[:MAX_TEXT_LENGTH]
            logging.warning(
                f"텍스트가 {MAX_TEXT_LENGTH}자를 초과하여 잘렸습니다."
            )

        resp = requests.post(
            f"{SUPERTONE_API_BASE}/v1/text-to-speech/{self._voice_id}",
            headers={
                "x-sup-api-key": self._api_key,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "language": self._lang,
                "model": self._model,
                "style": self._style,
                "output_format": "wav",
            },
            timeout=30,
        )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Supertone API 오류 ({resp.status_code}): {resp.text[:200]}"
            )

        # WAV 응답을 numpy 배열로 변환
        audio_bytes = io.BytesIO(resp.content)
        with wave.open(audio_bytes, "rb") as wf:
            sample_rate = wf.getframerate()
            n_frames = wf.getnframes()
            audio_data = wf.readframes(n_frames)
            sample_width = wf.getsampwidth()

        # int16로 변환
        if sample_width == 2:
            audio_np = np.frombuffer(audio_data, dtype=np.int16)
        elif sample_width == 4:
            audio_np = (
                np.frombuffer(audio_data, dtype=np.int32).astype(np.float64)
                / 2147483647
                * 32767
            ).astype(np.int16)
        else:
            audio_np = np.frombuffer(audio_data, dtype=np.int16)

        return audio_np, sample_rate

    def _worker(self) -> None:
        """백그라운드 워커: 큐에서 텍스트를 가져와 API로 합성 후 재생."""
        consecutive_errors: int = 0
        target_sample_rate: int = 48000

        while not self._stop_event.is_set():
            text: str | None = None
            try:
                text = self._queue.get(timeout=0.1)
                if text is None:
                    break

                self._is_speaking_event.set()

                # API로 음성 합성
                audio_int16, source_rate = self._synthesize_api(text)

                # 리샘플링 (API 출력 -> 48kHz)
                if source_rate != target_sample_rate:
                    from scipy.signal import resample

                    num_samples = round(
                        len(audio_int16) * target_sample_rate / source_rate
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
                logging.error(f"SupertonePlay TTS 오류: {e}")
                consecutive_errors += 1
                if consecutive_errors >= MAX_TTS_ERRORS:
                    logging.critical(
                        f"SupertonePlay TTS 연속 {MAX_TTS_ERRORS}회 오류. "
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
        self._queue.put(None)
        self._thread.join(timeout=5.0)

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
