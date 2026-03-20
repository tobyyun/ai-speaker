"""
providers/grok_tts_provider.py

Grok (xAI) TTS Provider - WebSocket 스트리밍.
WebSocket으로 텍스트를 보내고 오디오 청크를 실시간으로 받아 즉시 재생한다.
첫 청크부터 바로 재생하여 지연시간을 최소화한다.
"""

import asyncio
import base64
import json
import logging
import os
import queue
import threading
from argparse import Namespace

import numpy as np
import sounddevice as sd

from .base import TTSProvider
from ..audio_utils import MAX_TTS_ERRORS


class GrokTTSProvider(TTSProvider):
    """Grok (xAI) WebSocket 기반 TTS Provider.

    wss://api.x.ai/v1/tts 엔드포인트로 텍스트를 스트리밍하고,
    오디오 청크를 실시간으로 받아 즉시 재생한다.

    주요 특징:
        - WebSocket 스트리밍으로 초저지연 재생
        - PCM 포맷으로 디코딩 오버헤드 없음
        - 5개 음성 (ara, eve, leo, rex, sal)
        - 한국어 포함 20개 언어
        - $4.20/1M 글자 (가장 저렴)
    """

    def __init__(self, config: Namespace, interrupt_event: threading.Event) -> None:
        """Grok TTS Provider 초기화.

        Args:
            config: grok_tts_voice 등을 포함하는 설정 객체
            interrupt_event: 외부 인터럽트 이벤트

        Raises:
            ValueError: XAI_API_KEY가 설정되지 않은 경우
        """
        super().__init__(config, interrupt_event)

        self._queue: queue.Queue[str | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._is_speaking_event = threading.Event()
        self._has_failed = threading.Event()

        # API 키 확인
        self._api_key = os.environ.get("XAI_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "XAI_API_KEY가 설정되지 않았습니다. "
                ".env 파일에 XAI_API_KEY를 설정해주세요. "
                "API 키는 https://console.x.ai 에서 발급받을 수 있습니다."
            )

        # 설정
        self._voice: str = getattr(config, "grok_tts_voice", "sal")
        self._lang: str = getattr(config, "default_language", "ko")
        self._sample_rate: int = 24000
        self._output_device = getattr(config, "piper_output_device_index", None)

        logging.info(
            f"Grok TTS 초기화 완료. 음성: {self._voice}, "
            f"언어: {self._lang}, 샘플레이트: {self._sample_rate}Hz"
        )

        # 워커 스레드 시작
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _build_ws_uri(self) -> str:
        """WebSocket URI 생성."""
        return (
            f"wss://api.x.ai/v1/tts"
            f"?language={self._lang}"
            f"&voice={self._voice}"
            f"&codec=pcm"
            f"&sample_rate={self._sample_rate}"
        )

    async def _stream_tts(self, text: str) -> None:
        """WebSocket으로 텍스트를 보내고 오디오를 실시간 재생.

        첫 오디오 청크가 도착하면 즉시 재생을 시작한다.
        """
        import websockets

        uri = self._build_ws_uri()
        headers = {"Authorization": f"Bearer {self._api_key}"}

        try:
            async with websockets.connect(uri, additional_headers=headers) as ws:
                # 텍스트 전송
                await ws.send(json.dumps({
                    "type": "text.delta",
                    "delta": text,
                }))
                await ws.send(json.dumps({"type": "text.done"}))

                # 오디오 청크를 수신하며 버퍼에 누적 후 재생
                audio_buffer = bytearray()

                async for msg in ws:
                    if self.interrupt_event.is_set():
                        break

                    event = json.loads(msg)

                    if event["type"] == "audio.delta":
                        audio_buffer.extend(base64.b64decode(event["delta"]))

                    elif event["type"] == "audio.done":
                        break

                    elif event["type"] == "error":
                        raise RuntimeError(f"Grok TTS 서버 오류: {event.get('message', 'unknown')}")

                # 수신 완료 후 재생
                if audio_buffer and not self.interrupt_event.is_set():
                    audio_np = np.frombuffer(bytes(audio_buffer), dtype=np.int16)
                    duration_s = len(audio_np) / self._sample_rate
                    logging.info(
                        f"Grok TTS 오디오 수신 완료: {len(audio_buffer)} bytes, "
                        f"{len(audio_np)} samples, {duration_s:.2f}s, "
                        f"min={audio_np.min()}, max={audio_np.max()}, "
                        f"device={self._output_device}"
                    )

                    # 디버그: 첫 번째 오디오를 WAV로 저장
                    if self.config and getattr(self.config, 'debug', False):
                        import wave
                        with wave.open('/tmp/grok_tts_debug.wav', 'wb') as wf:
                            wf.setnchannels(1)
                            wf.setsampwidth(2)
                            wf.setframerate(self._sample_rate)
                            wf.writeframes(audio_np.tobytes())
                        logging.debug("디버그 오디오 저장: /tmp/grok_tts_debug.wav")

                    # OutputStream으로 직접 재생 (sd.play보다 신뢰성 높음)
                    import time as _time
                    with sd.OutputStream(
                        samplerate=self._sample_rate,
                        device=self._output_device,
                        channels=1,
                        dtype="int16",
                    ) as out_stream:
                        chunk_size = self._sample_rate // 10  # 100ms
                        for i in range(0, len(audio_np), chunk_size):
                            if self.interrupt_event.is_set():
                                break
                            out_stream.write(audio_np[i:i + chunk_size])
                        # 버퍼 드레인 대기
                        _time.sleep(0.3)
                    logging.debug("Grok TTS 재생 완료")

        except Exception as e:
            raise RuntimeError(f"Grok TTS WebSocket 오류: {e}") from e

    def _worker(self) -> None:
        """백그라운드 워커: 큐에서 텍스트를 가져와 WebSocket으로 합성 후 실시간 재생."""
        consecutive_errors: int = 0

        # 워커 전용 asyncio 이벤트 루프
        loop = asyncio.new_event_loop()

        while not self._stop_event.is_set():
            text: str | None = None
            try:
                text = self._queue.get(timeout=0.1)
                if text is None:
                    break

                self._is_speaking_event.set()

                # WebSocket 스트리밍 TTS 실행
                loop.run_until_complete(self._stream_tts(text))

                consecutive_errors = 0

            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"Grok TTS 오류: {e}")
                consecutive_errors += 1
                if consecutive_errors >= MAX_TTS_ERRORS:
                    logging.critical(
                        f"Grok TTS 연속 {MAX_TTS_ERRORS}회 오류. "
                        f"TTS를 비활성화합니다."
                    )
                    self._has_failed.set()
                    break
            finally:
                if text is not None:
                    self._queue.task_done()
                if self._queue.empty():
                    self._is_speaking_event.clear()

        loop.close()

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
