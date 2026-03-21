import logging
import threading
import time
import numpy as np
import sounddevice as sd
import os
import gc
import re

# 서브모듈 임포트
from .audio_input import AudioInput
from .providers import ProviderFactory
from .audio_utils import SENTENCE_END_PUNCTUATION, RATE, INT16_MAX, monitor_memory
from .tools import load_state, set_name_changed_callback

class VoiceAssistant:
    def __init__(self, args, client=None):
        self.args = args
        self.interrupt_event = threading.Event()
        self.conversation_count = 0
        self.is_handling_conversation = False

        # 웨이크워드 감지 설정
        self.last_wakeword_time = 0
        self.wakeword_cooldown = 1.0
        self.consecutive_detection_count = 0
        self.required_consecutive = 1

        # 웨이크워드 모드: "model" (OpenWakeWord ONNX) 또는 "stt" (STT 기반)
        self.wakeword_mode = getattr(args, "wakeword_mode", "model")

        # 상태 파일에서 이름/웨이크워드 로드 (사용자가 이름을 바꿨을 수 있음)
        state = load_state()
        saved_wakeword = state.get("wakeword", "")
        if saved_wakeword:
            self.wakeword_text = saved_wakeword
        else:
            self.wakeword_text = getattr(args, "wakeword", "hey jarvis").strip()
        self.assistant_name = state.get("name", "챱츄")
        self.wakeword_chosung = self._extract_chosung(self.wakeword_text)

        # 이름 변경 콜백 등록 (도구에서 이름 변경 시 런타임 업데이트)
        set_name_changed_callback(self._on_name_changed)

        logging.debug(f"VoiceAssistant init - wakeword_mode: {self.wakeword_mode}, name: '{self.assistant_name}', wakeword: '{self.wakeword_text}', chosung: '{self.wakeword_chosung}'")

        # 서브시스템 초기화 (Provider 팩토리를 통해 생성)
        self.audio = AudioInput(args)

        llm_provider_name = getattr(args, "llm_provider", "ollama")
        tts_provider_name = getattr(args, "tts_provider", "piper")
        stt_provider_name = getattr(args, "stt_provider", "whisper")

        self.transcriber = ProviderFactory.create_stt(stt_provider_name, args)
        self.tts = ProviderFactory.create_tts(tts_provider_name, args, self.interrupt_event)
        self.llm = ProviderFactory.create_llm(llm_provider_name, args)

        # Wakeword Setup (model 모드에서만 ONNX 모델 로드)
        self.oww_model = None
        self.wakeword_key = None
        if self.wakeword_mode == "model":
            try:
                from openwakeword.model import Model
                if not os.path.exists(args.wakeword_model_path):
                    raise FileNotFoundError(f"Wakeword model missing: {args.wakeword_model_path}")
                logging.debug(f"Loading wakeword model from: {args.wakeword_model_path}")
                self.oww_model = Model(wakeword_model_paths=[args.wakeword_model_path])
                self.wakeword_key = list(self.oww_model.models.keys())[0]
                logging.debug(f"Wakeword model loaded with key: {self.wakeword_key}")
            except Exception as e:
                logging.warning(f"OpenWakeWord 모델 로드 실패, STT 모드로 전환: {e}")
                self.wakeword_mode = "stt"

        if self.wakeword_mode == "stt":
            logging.info(f"STT 기반 웨이크워드 모드. 웨이크워드: '{self.wakeword_text}'")

    def run(self):
        logging.info(f"Ready! Listening for '{self.args.wakeword}'...")
        self.audio.start()

        try:
            if self.wakeword_mode == "stt":
                self._run_stt_wakeword()
            else:
                self._run_model_wakeword()
        except KeyboardInterrupt:
            logging.info("Stopping...")
        self.cleanup()

    def _run_stt_wakeword(self):
        """STT 기반 웨이크워드 감지 루프.

        VAD로 음성을 감지하면 짧게 녹음 → whisper로 인식 → 웨이크워드 매칭.
        """
        while True:
            if self.is_handling_conversation:
                time.sleep(0.01)
                continue

            # VAD로 짧은 음성 녹음 (웨이크워드 감지용, 최대 3초)
            audio_np = self.audio.record_phrase(
                self.interrupt_event,
                timeout_seconds=self.args.listen_timeout,
            )

            if audio_np is None:
                continue

            # 너무 짧은 오디오 무시 (0.3초 미만)
            duration = len(audio_np) / RATE
            if duration < 0.3:
                continue

            # 빠른 STT 인식
            user_text = self.transcriber.transcribe(audio_np)
            del audio_np

            if not user_text or not user_text.strip():
                continue

            user_text_lower = user_text.strip().lower()
            logging.debug(f"STT 웨이크워드 감지: '{user_text_lower}'")

            # 웨이크워드 매칭 (초성 유사도 기반)
            if not self._is_wakeword_match(user_text.strip()):
                logging.debug(f"웨이크워드 불일치: '{user_text_lower}'")
                continue

            current_time = time.time()
            if current_time - self.last_wakeword_time < self.wakeword_cooldown:
                continue

            logging.info(f"웨이크워드 감지됨! (STT: '{user_text.strip()}')")
            self.last_wakeword_time = current_time

            # 웨이크워드 뒤에 명령어가 포함되어 있는지 확인
            command_text = self._extract_command_after_wakeword(user_text.strip())

            self.is_handling_conversation = True
            if command_text:
                logging.info(f"웨이크워드와 함께 명령 감지: '{command_text}'")
                self._handle_conversation(prerecorded_text=command_text)
            else:
                self._handle_conversation()

            # 연속 대화 모드: 대화 후 일정 시간 동안 웨이크워드 없이 계속 대화
            follow_up_timeout = getattr(self.args, "follow_up_seconds", 10)
            while follow_up_timeout > 0:
                logging.info(f"연속 대화 대기 중... ({follow_up_timeout}초)")
                self.audio.start()
                follow_start = time.time()

                audio_np = self.audio.record_phrase(
                    self.interrupt_event,
                    timeout_seconds=follow_up_timeout,
                )

                elapsed = time.time() - follow_start

                if audio_np is None:
                    # 타임아웃 - 아무 말 없으면 연속 대화 종료
                    logging.debug("연속 대화 타임아웃, 대기 모드로 복귀")
                    break

                duration = len(audio_np) / RATE
                if duration < 0.3:
                    follow_up_timeout -= elapsed
                    continue

                # 추가 발화 감지 - 웨이크워드 없이 바로 대화 처리
                user_text = self.transcriber.transcribe(audio_np)
                del audio_np

                if not user_text or not user_text.strip():
                    follow_up_timeout -= elapsed
                    continue

                logging.info(f"연속 대화 감지: '{user_text.strip()}'")
                self.audio.stop()
                self._handle_conversation(prerecorded_text=user_text.strip())
                # 연속 대화 타이머 리셋
                follow_up_timeout = getattr(self.args, "follow_up_seconds", 10)

            logging.info(f"Ready! Listening for '{self.args.wakeword}'...")

    def _extract_command_after_wakeword(self, text: str) -> str:
        """웨이크워드 뒤에 오는 명령어 텍스트를 추출.

        한국어 웨이크워드 길이(3글자)만큼 건너뛰고 나머지를 반환한다.
        쉼표, 마침표, 공백 등을 정리한다.
        """
        korean_chars = [(i, ch) for i, ch in enumerate(text) if 0xAC00 <= ord(ch) <= 0xD7A3]
        ww_len = len(self.wakeword_text)

        if len(korean_chars) <= ww_len:
            return ""

        # 웨이크워드 끝 위치 이후의 텍스트 추출
        end_idx = korean_chars[ww_len - 1][0] + 1
        remaining = text[end_idx:].lstrip(" ,.\t")

        if len(remaining) > 2:
            return remaining
        return ""

    def _run_model_wakeword(self):
        """OpenWakeWord ONNX 모델 기반 웨이크워드 감지 루프."""
        score_history = []
        weighted_scores = []

        while True:
            if self.is_handling_conversation:
                time.sleep(0.01)
                continue

            chunk = self.audio.get_chunk()
            if not chunk:
                time.sleep(0.001)
                continue

            int16_audio = np.frombuffer(chunk, dtype=np.int16)
            prediction = self.oww_model.predict(int16_audio)
            score = prediction.get(self.wakeword_key, 0)

            score_history.append(score)
            if len(score_history) > 100:
                score_history.pop(0)

            current_time = time.time()
            weighted_scores.append(score)
            if len(weighted_scores) > 5:
                weighted_scores.pop(0)
            avg_score = sum(weighted_scores) / len(weighted_scores)

            if score > self.args.wakeword_threshold:
                if current_time - self.last_wakeword_time > self.wakeword_cooldown:
                    self.consecutive_detection_count += 1

                    logging.debug(f"Wakeword candidate (score: {score:.2f}, consecutive: {self.consecutive_detection_count}/{self.required_consecutive})")

                    if self.consecutive_detection_count >= self.required_consecutive:
                        recent_scores = [f"{s:.2f}" for s in score_history[-10:]]
                        logging.info(f"Wakeword detected! (score: {score:.2f}, recent: {', '.join(recent_scores)})")

                        self.last_wakeword_time = current_time
                        self.consecutive_detection_count = 0
                        weighted_scores.clear()
                        self.oww_model.reset()

                        self.is_handling_conversation = True
                        self._handle_conversation()

                        self.oww_model.reset()
                        self.consecutive_detection_count = 0
                        weighted_scores.clear()
                        score_history.clear()
                        logging.info(f"Ready! Listening for '{self.args.wakeword}'...")
            else:
                if self.consecutive_detection_count > 0:
                    self.consecutive_detection_count = 0

    # 한국어 초성 테이블
    _CHOSUNG = [
        'ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ',
        'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ',
    ]
    # 유사 초성 그룹 (같은 그룹이면 매칭 허용)
    # whisper가 한국어 자음을 혼동하는 패턴을 반영하여 넓게 설정
    _SIMILAR_CHOSUNG = {
        # 치경/경구개 그룹: ㅈ,ㅉ,ㅊ,ㅌ,ㄷ,ㄸ (whisper가 자주 혼동)
        'ㅈ': {'ㅈ', 'ㅉ', 'ㅊ', 'ㅌ', 'ㄷ', 'ㄸ'},
        'ㅉ': {'ㅈ', 'ㅉ', 'ㅊ', 'ㅌ', 'ㄷ', 'ㄸ'},
        'ㅊ': {'ㅈ', 'ㅉ', 'ㅊ', 'ㅌ', 'ㄷ', 'ㄸ'},
        'ㅌ': {'ㅈ', 'ㅉ', 'ㅊ', 'ㅌ', 'ㄷ', 'ㄸ'},
        'ㄷ': {'ㅈ', 'ㅉ', 'ㅊ', 'ㅌ', 'ㄷ', 'ㄸ'},
        'ㄸ': {'ㅈ', 'ㅉ', 'ㅊ', 'ㅌ', 'ㄷ', 'ㄸ'},
        # 양순음 그룹: ㅂ,ㅃ,ㅍ
        'ㅂ': {'ㅂ', 'ㅃ', 'ㅍ'},
        'ㅃ': {'ㅂ', 'ㅃ', 'ㅍ'},
        'ㅍ': {'ㅂ', 'ㅃ', 'ㅍ'},
        # 연구개음 그룹: ㄱ,ㄲ,ㅋ
        'ㄱ': {'ㄱ', 'ㄲ', 'ㅋ'},
        'ㄲ': {'ㄱ', 'ㄲ', 'ㅋ'},
        'ㅋ': {'ㄱ', 'ㄲ', 'ㅋ'},
        # 치찰음 그룹: ㅅ,ㅆ
        'ㅅ': {'ㅅ', 'ㅆ'},
        'ㅆ': {'ㅅ', 'ㅆ'},
    }

    def _extract_chosung(self, text: str) -> str:
        """한국어 텍스트에서 초성만 추출. 비한글은 무시."""
        result = []
        for ch in text:
            code = ord(ch) - 0xAC00
            if 0 <= code < 11172:
                result.append(self._CHOSUNG[code // 588])
        return ''.join(result)

    def _is_wakeword_match(self, text: str) -> bool:
        """STT 인식 텍스트에서 웨이크워드를 유사도 기반으로 매칭.

        3글자 한국어 단어의 초성을 비교하여 유사 발음을 허용한다.
        예: "챱츄야" 초성 ㅊㅊㅇ ≈ "접추야" 초성 ㅈㅊㅇ (ㅈ≈ㅊ 유사)
        """
        text_lower = text.lower().strip()

        # 영어 웨이크워드는 단순 포함 매칭
        ww = self.wakeword_text.lower()
        if not any(0xAC00 <= ord(c) <= 0xD7A3 for c in ww):
            return ww in text_lower

        # 한국어: 텍스트에서 단어 단위로 초성 비교
        target_chosung = self.wakeword_chosung
        target_len = len(target_chosung)

        if target_len == 0:
            return False

        # 텍스트에서 한국어 글자만 추출하여 슬라이딩 윈도우 매칭
        korean_chars = [ch for ch in text if 0xAC00 <= ord(ch) <= 0xD7A3]

        for i in range(len(korean_chars) - len(self.wakeword_text) + 1):
            window = korean_chars[i:i + len(self.wakeword_text)]
            window_chosung = self._extract_chosung(''.join(window))

            if len(window_chosung) != target_len:
                continue

            # 초성 유사도 비교: 유사 그룹 불일치 1개까지 허용 (관대 설정)
            mismatch = 0
            for c1, c2 in zip(target_chosung, window_chosung):
                if c1 == c2:
                    continue
                similar = self._SIMILAR_CHOSUNG.get(c1, {c1})
                if c2 in similar:
                    continue  # 유사 그룹이면 OK
                mismatch += 1

            # 마지막 글자(야)는 ㅇ이어야 함 (기본 필터)
            last_ok = target_chosung[-1] == window_chosung[-1] if target_len > 0 else True

            if mismatch <= 1 and last_ok:
                logging.debug(
                    f"초성 매칭 성공: '{self.wakeword_text}'({target_chosung}) ≈ "
                    f"'{''.join(window)}'({window_chosung}) [불일치:{mismatch}]"
                )
                return True

        return False

    def _start_thinking_sound(self) -> None:
        """Thinking 사운드를 백그라운드에서 루프 재생."""
        thinking_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "assets", "thinking.mp3"
        )
        if not os.path.exists(thinking_path):
            logging.debug(f"Thinking 사운드 파일 없음: {thinking_path}")
            return

        self._thinking_stop = threading.Event()

        def _play_loop():
            try:
                import soundfile as sf
                data, samplerate = sf.read(thinking_path, dtype="int16")

                # 스테레오면 모노로 변환
                if len(data.shape) > 1:
                    data = data.mean(axis=1).astype(np.int16)

                output_device = getattr(self.args, "piper_output_device_index", None)
                chunk_size = samplerate // 10  # 100ms

                # 스트림을 한 번만 열고 루프 재생
                with sd.OutputStream(
                    samplerate=samplerate,
                    device=output_device,
                    channels=1,
                    dtype="int16",
                ) as stream:
                    while not self._thinking_stop.is_set():
                        for i in range(0, len(data), chunk_size):
                            if self._thinking_stop.is_set():
                                return
                            stream.write(data[i:i + chunk_size])

            except Exception as e:
                logging.debug(f"Thinking 사운드 재생 오류: {e}")

        self._thinking_thread = threading.Thread(target=_play_loop, daemon=True)
        self._thinking_thread.start()
        logging.debug("Thinking 사운드 시작")

    def _stop_thinking_sound(self) -> None:
        """Thinking 사운드 정지."""
        if hasattr(self, "_thinking_stop") and self._thinking_stop:
            self._thinking_stop.set()
        if hasattr(self, "_thinking_thread") and self._thinking_thread:
            self._thinking_thread.join(timeout=2.0)
            self._thinking_thread = None
        logging.debug("Thinking 사운드 정지")

    def _on_name_changed(self, new_name: str, new_wakeword: str) -> None:
        """이름 변경 콜백. 도구에서 이름 변경 시 런타임으로 웨이크워드 업데이트."""
        self.assistant_name = new_name
        self.wakeword_text = new_wakeword
        self.wakeword_chosung = self._extract_chosung(new_wakeword)
        logging.info(
            f"웨이크워드 런타임 업데이트: '{new_wakeword}' (초성: {self.wakeword_chosung})"
        )

    def _monitor_barge_in(self) -> str | None:
        """TTS 재생 중 사용자 음성을 감지하여 바지인 처리.

        TTS가 재생되는 동안 마이크를 모니터링하고,
        VAD가 일정 시간 이상 음성을 감지하면 TTS를 중단하고
        사용자의 발화를 녹음/인식한다.

        Returns:
            사용자 발화 텍스트, 또는 바지인 없이 TTS 완료 시 None
        """
        import webrtcvad

        self.audio.start()
        vad = webrtcvad.Vad(0)  # 가장 낮은 공격성
        speech_chunks = 0
        required_speech_chunks = 40  # ~1.2초 연속 음성 감지 시 바지인
        barge_in_delay = 3.0  # TTS 시작 후 이 시간(초)은 바지인 무시
        energy_threshold = 0.03  # 스피커 에코보다 높은 에너지만 감지
        monitor_start = time.time()

        # 처음 N초간은 에코 에너지 기준선 측정
        echo_energy_samples = []

        while self.tts.is_speaking:
            chunk = self.audio.get_chunk(timeout=0.03)
            if not chunk:
                continue

            elapsed = time.time() - monitor_start

            # 오디오 에너지 계산
            audio_data = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / INT16_MAX
            chunk_energy = np.sqrt(np.mean(audio_data ** 2))

            # 처음 2초간 에코 에너지 기준선 수집
            if elapsed < 2.0:
                echo_energy_samples.append(chunk_energy)
                continue

            # 에코 기준선 계산 (평균 + 여유분)
            if echo_energy_samples:
                echo_baseline = (sum(echo_energy_samples) / len(echo_energy_samples)) * 2.0
                echo_energy_samples = []  # 한 번만 계산
            elif not hasattr(self, '_echo_baseline'):
                echo_baseline = energy_threshold
            else:
                echo_baseline = self._echo_baseline
            self._echo_baseline = echo_baseline

            # 바지인 지연 시간 내에는 무시
            if elapsed < barge_in_delay:
                continue

            try:
                is_speech = vad.is_speech(chunk, RATE)
            except Exception:
                continue

            # VAD + 에너지 임계값 둘 다 통과해야 함
            if is_speech and chunk_energy > max(echo_baseline, energy_threshold):
                speech_chunks += 1
                if speech_chunks >= required_speech_chunks:
                    logging.info(
                        f"바지인 감지! (에너지: {chunk_energy:.4f}, "
                        f"기준: {echo_baseline:.4f}, 경과: {elapsed:.1f}초)"
                    )
                    self.interrupt_event.set()
                    self.tts.clear_queue()

                    time.sleep(0.2)
                    self.interrupt_event.clear()

                    # 사용자 발화 녹음
                    audio_np = self.audio.record_phrase(
                        self.interrupt_event, self.args.listen_timeout
                    )
                    self.audio.stop()

                    if audio_np is None or len(audio_np) / RATE < 0.3:
                        return None

                    user_text = self.transcriber.transcribe(audio_np)
                    del audio_np

                    if user_text and user_text.strip():
                        return user_text.strip()
                    return None
            else:
                speech_chunks = max(0, speech_chunks - 2)

        self.audio.stop()
        return None

    def _process_plugins(self, text: str) -> str:
        """Processes simple plugins like [current time]."""
        if "[current time]" in text.lower():
            current_time = time.strftime("%I:%M %p")
            logging.debug(f"Plugin found: [current time] -> {current_time}")
            # Use regex for case-insensitive replacement
            text = re.sub(r'\[current time\]', current_time, text, flags=re.IGNORECASE)
        return text

    def _handle_conversation(self, prerecorded_text: str | None = None):
        try:
            conversation_start = time.time()

            # Optional memory profiling
            mem_before = 0
            if self.args.debug and self.args.memory_profiling:
                mem_before = monitor_memory()
                logging.debug(f"Memory at conversation start: {mem_before:.2f} MB")

            self.audio.stop()
            self.audio.clear_buffer()

            # prerecorded_text가 있으면 녹음/인식 건너뛰기
            if prerecorded_text:
                user_text = prerecorded_text
                self.interrupt_event.clear()
                # "Yes?" 확인음 대신 바로 처리
            else:
                logging.debug("Playing acknowledgment")
                self.tts.speak("네?")
                self.tts.wait_until_done()

                self.interrupt_event.clear()

                # Start listening for command
                logging.debug("Starting audio recording for command")
                self.audio.start()

            if not prerecorded_text:
                # 녹음 및 인식 (prerecorded_text가 없을 때만)
                time.sleep(0.4)

                recording_start = time.time()
                audio_np = self.audio.record_phrase(self.interrupt_event, self.args.listen_timeout)
                recording_duration = time.time() - recording_start

                self.audio.stop()

                if audio_np is None:
                    logging.debug(f"No audio recorded (recording took {recording_duration:.2f}s)")
                    self.audio.start()
                    return

                logging.debug(f"Audio recording completed in {recording_duration:.2f}s")

                audio_rms = np.sqrt(np.mean(audio_np**2))
                audio_peak = np.max(np.abs(audio_np))
                audio_std = np.std(audio_np)
                logging.debug(f"Audio quality - RMS: {audio_rms:.4f}, Peak: {audio_peak:.4f}, StdDev: {audio_std:.4f}")

                if audio_rms < 0.01:
                    logging.warning(f"Audio too quiet (RMS: {audio_rms:.4f}), proceeding to transcription")
                if audio_std < 0.005:
                    logging.warning(f"Audio lacks variation (StdDev: {audio_std:.4f}), likely silence, proceeding to transcription")
                if audio_peak > 0.98:
                    logging.warning(f"Audio may be clipping (Peak: {audio_peak:.4f})")

                transcription_start = time.time()
                user_text = self._transcribe_with_retry(audio_np)
                transcription_duration = time.time() - transcription_start
                logging.debug(f"Transcription completed in {transcription_duration:.2f}s")

                del audio_np

                if not user_text or not user_text.strip():
                    logging.debug("Transcription was empty or whitespace only")
                    self.audio.start()
                    return
    
            # Trim wake word if enabled
            original_text = user_text
            if self.args.trim_wake_word:
                user_text = self._trim_wakeword(user_text)
                if user_text != original_text:
                    logging.debug(f"Wake word trimmed: '{original_text}' -> '{user_text}'")
    
            # If the command is now empty, do nothing
            if not user_text or not user_text.strip():
                logging.debug("Command empty after wake word trimming")
                self.audio.start()
                return
    
            # Take only the first sentence
            sentences = re.split(r'(?<=[.?!])\s+', user_text)
            if sentences:
                first_sentence = sentences[0]
                if first_sentence != user_text:
                    logging.debug(f"Using first sentence only: '{first_sentence}'")
                    user_text = first_sentence

            # Process any plugins
            user_text = self._process_plugins(user_text)

            logging.info(f"You: {user_text}")

            # Check for exit commands
            user_text_lower = user_text.lower()
            if "exit" in user_text_lower or "goodbye" in user_text_lower:
                logging.debug("Exit command detected")
                self.tts.speak("Goodbye.")
                self.tts.wait_until_done()
                exit(0)
    
            # Check for history reset commands
            if "new chat" in user_text_lower or "reset chat" in user_text_lower:
                logging.debug("Chat reset command detected")
                self.llm.reset_history()
                self.tts.speak("Chat history cleared.")
                self.tts.wait_until_done()
                self.audio.start()
                return
    
            # Thinking 사운드 루프 재생 시작
            self._start_thinking_sound()

            # LLM 응답을 전체 수신 후 한 번에 TTS로 전달
            logging.debug("Sending to LLM")
            llm_start = time.time()
            full_response = ""
            token_count = 0

            for token in self.llm.chat_stream(user_text):
                if token is None:
                    logging.error("LLM returned None token")
                    break
                if self.interrupt_event.is_set():
                    logging.debug("Conversation interrupted")
                    break

                token_count += 1
                full_response += token

            # Thinking 사운드 정지
            self._stop_thinking_sound()

            llm_duration = time.time() - llm_start
            logging.debug(f"LLM streaming completed in {llm_duration:.2f}s ({token_count} tokens)")

            # 전체 응답을 한 번에 TTS로 전달
            full_response = full_response.strip()
            barge_in_text = None
            if full_response and not self.interrupt_event.is_set():
                logging.info(f"Assistant: {full_response}")
                self.tts.speak(full_response)

                # 바지인 감지: TTS 재생 중 마이크로 사용자 음성을 모니터링
                barge_in_text = self._monitor_barge_in()

            if barge_in_text is None:
                # 바지인 없이 정상 완료 - TTS 끝날 때까지 대기
                self.tts.wait_until_done()

            # After conversation completes
            self.conversation_count += 1
            conversation_duration = time.time() - conversation_start
            
            logging.debug(f"Conversation #{self.conversation_count} completed in {conversation_duration:.2f}s")
            
            # Periodic aggressive cleanup
            if self.args.gc_interval > 0 and self.conversation_count % self.args.gc_interval == 0:
                gc.collect()
                logging.debug(f"Periodic garbage collection triggered (every {self.args.gc_interval} conversations)")
    
            # Optional memory profiling
            if self.args.debug and self.args.memory_profiling and mem_before > 0:
                mem_after = monitor_memory()
                mem_delta = mem_after - mem_before
                logging.debug(f"Memory at conversation end: {mem_after:.2f} MB (delta: {mem_delta:+.2f} MB)")
                
            self.audio.start()

            # 바지인으로 중단된 경우 즉시 새 대화 시작
            if barge_in_text:
                logging.info(f"바지인 대화: '{barge_in_text}'")
                self._handle_conversation(prerecorded_text=barge_in_text)
        finally:
            self.is_handling_conversation = False

    def _transcribe_with_retry(self, audio_np: np.ndarray, max_retries: int = 3) -> str:
        """Transcribe with progressive threshold relaxation and better logging."""
        original_logprob = self.args.whisper_avg_logprob
        original_nospeech = self.args.whisper_no_speech_prob
        
        # Define threshold progression
        threshold_steps = [
            (original_logprob, original_nospeech),
            (original_logprob - 0.15, original_nospeech + 0.1),
            (original_logprob - 0.3, original_nospeech + 0.2),
        ]
        
        logging.debug(f"Starting transcription (initial thresholds: logprob={original_logprob}, no_speech={original_nospeech})")
        
        for attempt in range(min(max_retries, len(threshold_steps))):
            logprob_threshold, nospeech_threshold = threshold_steps[attempt]
            
            # Update thresholds
            self.args.whisper_avg_logprob = logprob_threshold
            self.args.whisper_no_speech_prob = nospeech_threshold
            
            logging.debug(f"Transcription attempt {attempt + 1}/{max_retries} (logprob={logprob_threshold:.2f}, no_speech={nospeech_threshold:.2f})")
            
            user_text = self.transcriber.transcribe(audio_np)
            
            if user_text and user_text.strip():
                logging.debug(f"Transcription successful on attempt {attempt + 1}: '{user_text}'")
                # Restore original thresholds
                self.args.whisper_avg_logprob = original_logprob
                self.args.whisper_no_speech_prob = original_nospeech
                return user_text
            
            if attempt < max_retries - 1:
                logging.debug(f"Attempt {attempt + 1} failed, trying with relaxed thresholds")
        
        # Restore original thresholds
        self.args.whisper_avg_logprob = original_logprob
        self.args.whisper_no_speech_prob = original_nospeech
        
        logging.warning(f"All {max_retries} transcription attempts failed")
        return ""

    def _trim_wakeword(self, text: str) -> str:
        """Trims the wake word from the transcription using regex for robustness."""
        wakeword = self.args.wakeword.lower()
        text_lower = text.lower().strip()

        # Generate a list of core wake word names (e.g., "jarvis" from "hey jarvis")
        # and common misspellings/pronunciations that should be trimmed.
        # This list should NOT contain partial words that could lead to over-trimming.
        core_wakeword_names = ["jarvis", "jarlis", "jarvas", "jarves", "jarvys", "jarvois"]
        
        # Add the exact configured wake word to the patterns, in case it's a multi-word phrase
        patterns_to_match = [re.escape(wakeword)] # Escape for regex safety
        
        # Add patterns for common prefixes/suffixes around the core names
        for name in core_wakeword_names:
            patterns_to_match.append(r"(?:hey\s*)?" + re.escape(name)) # Optional "hey "
            patterns_to_match.append(re.escape(name)) # Just the name

        # Create a single regex pattern to match any of these at the start or end,
        # with optional punctuation and spaces. Use word boundaries where appropriate.
        # This regex will look for the pattern either at the beginning (^) or the end ($)
        # of the string, allowing for flexible matching.
        
        # Example: if wakeword is "hey jarvis"
        # patterns_to_match could be: ["hey\\s*jarvis", "hey\\s*jarlis", ..., "jarvis", "jarlis", ...]
        
        # Construct the full regex:
        # 1. Match at the beginning: (?:<pattern>)\b[.,!?]*\s*
        # 2. Match at the end: \s*\b(?:<pattern>)[.,!?]*$
        
        # To avoid over-trimming, ensure word boundaries (\b) are used where logical.
        # Also, make sure the most specific patterns are tried first if using an OR separated list.
        
        # For simplicity and to avoid complex lookarounds, we'll try to find the longest match first
        # and then trim. A single regex can be structured to capture the matched wake word part.
        
        # Let's build a regex that captures the wake word part we want to remove.
        # We need to ensure we don't accidentally trim valid speech that happens to contain
        # a wake word component.
        
        # Pattern for matching at the beginning (case-insensitive)
        # e.g., "hey jarvis, what time" -> "what time"
        # (?:^|\s) ensures we match at the start or after a space, \b for word boundary
        combined_start_pattern = r"^(?:" + "|".join(patterns_to_match) + r")\b[.,!?]*\s*"
        match_start = re.match(combined_start_pattern, text_lower, re.IGNORECASE)
        if match_start:
            trimmed_text = text[len(match_start.group(0)):].strip()
            logging.debug(f"Wake word trimmed from start: '{match_start.group(0)}' removed. Result: '{trimmed_text}'")
            return trimmed_text
            
        # Pattern for matching at the end (case-insensitive)
        # e.g., "what time hey jarvis" -> "what time"
        combined_end_pattern = r"\s*\b(?:" + "|".join(patterns_to_match) + r")[.,!?]*$"
        match_end = re.search(combined_end_pattern, text_lower, re.IGNORECASE)
        if match_end:
            trimmed_text = text[:match_end.start()].strip()
            logging.debug(f"Wake word trimmed from end: '{match_end.group(0)}' removed. Result: '{trimmed_text}'")
            return trimmed_text

        logging.debug("No wake word pattern found, keeping original text")
        return text

    def cleanup(self):
        """모든 서브시스템 리소스 정리."""
        logging.debug("Starting cleanup")
        self.audio.stop()
        self.tts.stop()
        self.transcriber.close()
        if hasattr(self, 'llm') and self.llm is not None:
            self.llm.close()
        logging.debug("Cleanup complete")
