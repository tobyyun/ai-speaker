---
id: SPEC-VOICE-001
type: plan
version: "1.0.0"
status: draft
created: "2026-03-19"
updated: "2026-03-19"
author: toby
---

# SPEC-VOICE-001 구현 계획

## 1. 구현 개요

기존 Ollama + Piper TTS 기반 영어 음성 비서를 Claude API + Supertonic TTS 기반 한국어 음성 비서로 전환한다. SPEC-PROVIDER-001이 제공하는 Provider 추상화 계층 위에 구체적인 Provider 구현체를 생성한다.

## 2. 마일스톤

### 마일스톤 1: Claude LLM Provider 구현 [최우선]

**목표**: Claude Sonnet API를 기본 LLM Provider로 동작시킨다.

**산출물**: `src/voice_assistant/providers/claude_provider.py`

**구현 내용**:

1. `LLMProvider` ABC 구현
   - `__init__`: `anthropic.Anthropic()` 클라이언트 초기화, API 키 검증
   - `chat_stream(user_text: str) -> Generator[str, None, None]`: 스트리밍 응답
   - `reset_history()`: 대화 히스토리 초기화
   - `_prune_history()`: 기존 `LLMHandler` 패턴 유지

2. 스트리밍 구현 세부사항
   - `client.messages.stream()` 사용
   - `model="claude-sonnet-4-20250514"` 지정
   - `max_tokens` 설정 (음성 응답에 적합하도록 256~512)
   - 토큰 단위 yield로 기존 `voice_assistant.py`의 문장 버퍼링 패턴과 호환

3. 에러 처리
   - `anthropic.APIConnectionError`: 네트워크 에러 로깅 후 `None` yield
   - `anthropic.RateLimitError`: 재시도 로직 (최대 3회, 지수 백오프)
   - `anthropic.AuthenticationError`: API 키 에러 명확히 로깅
   - API 키 값이 로그에 포함되지 않도록 마스킹 처리

4. 한국어 시스템 프롬프트
   - 기본값: "당신은 똑똑하고 재치 있는 한국어 음성 비서입니다. 모든 응답은 간결하게 한두 문장으로 해주세요."
   - `config.ini`에서 오버라이드 가능

**참조 코드**: 기존 `llm_handler.py`의 `chat_stream()` 패턴, `_prune_history()` 로직

---

### 마일스톤 2: Supertonic TTS Provider 구현 [최우선]

**목표**: Supertonic을 기본 TTS Provider로 동작시킨다.

**산출물**: `src/voice_assistant/providers/supertonic_provider.py`

**구현 내용**:

1. `TTSProvider` ABC 구현
   - `__init__`: `TTS(auto_download=True)` 초기화, 음성 스타일 로드
   - `speak(text: str)`: 큐에 텍스트 추가
   - `stop()`: 리소스 정리
   - `clear_queue()`: 큐 비우기
   - `is_speaking` 속성: 현재 발화 상태

2. Supertonic 초기화
   - `from supertonic import TTS`
   - `tts = TTS(auto_download=True)` - 모델 자동 다운로드
   - `voice = tts.get_voice_style(voice_name="F3")` - 한국어 여성 음성
   - 초기화 실패 시 `has_failed` 이벤트 설정 (기존 `Synthesizer` 패턴)

3. 오디오 출력 패턴 (기존 `Synthesizer._worker` 참조)
   - `threading.Thread(target=self._worker, daemon=True)`로 백그라운드 워커
   - `queue.Queue()`로 문장 큐 관리
   - `sounddevice.OutputStream`으로 오디오 출력
   - `tts.synthesize(text, voice)` 결과를 numpy 배열로 변환
   - 필요 시 `scipy.signal.resample`로 리샘플링 (Supertonic 출력 샘플레이트 확인 필요)
   - `interrupt_event` 체크로 인터럽트 지원

4. 에러 처리
   - 모델 다운로드 실패: 명확한 에러 메시지
   - 연속 에러 카운터 (기존 `MAX_TTS_ERRORS` 패턴)
   - 리소스 정리: `stop()` 시 워커 스레드 종료 및 모델 해제

**참조 코드**: 기존 `synthesizer.py`의 전체 구조 (큐, 워커, 인터럽트, 리샘플링)

---

### 마일스톤 3: 한국어 STT 설정 변경 [높은 우선순위]

**목표**: faster-whisper를 한국어 인식으로 전환한다.

**변경 파일**: `config.ini`, `src/voice_assistant/transcriber.py`

**구현 내용**:

1. `config.ini` 변경
   - `whisper_model`: `small.en` -> `small` (다국어 모델)
   - 새로운 설정 추가: `language = ko`

2. `transcriber.py` 변경
   - `self.model.transcribe()` 호출 시 `language="en"` -> `language="ko"`로 변경
   - 또는 `config.ini`의 `language` 설정값을 동적으로 참조
   - 한국어 인식 임계값 조정:
     - `whisper_avg_logprob`: `-1.0` -> `-1.2` (한국어는 log probability가 낮을 수 있음)
     - `whisper_no_speech_prob`: `0.65` -> `0.7` (한국어 특성 반영)

3. 한국어 문장 종결 부호 지원
   - `audio_utils.py`의 `SENTENCE_END_PUNCTUATION`에 한국어 부호 확인
   - 필요 시 마침표(.), 물음표(?), 느낌표(!) 외에 한국어 특수 부호 추가

**참조 코드**: 기존 `transcriber.py`의 `_internal_transcribe()`, `config.ini`

---

### 마일스톤 4: config.ini 및 설정 통합 [높은 우선순위]

**목표**: 새로운 Provider 설정을 config.ini와 config_manager.py에 통합한다.

**변경 파일**: `config.ini`, `src/voice_assistant/config_manager.py`

**구현 내용**:

1. `config.ini` 새 필드 추가
   ```ini
   [Models]
   llm_provider = claude
   tts_provider = supertonic
   language = ko
   ```

2. `config_manager.py` 변경
   - 새로운 argparse 인수 추가: `--llm-provider`, `--tts-provider`, `--language`
   - `DEFAULT_SETTINGS`에 새 기본값 추가
   - Ollama 클라이언트 생성을 조건부로 변경 (provider가 ollama일 때만)
   - `.env` 파일 로드 로직 추가 (`python-dotenv`)

3. Provider 팩토리 연결
   - `config_manager.py`에서 선택된 provider 이름을 `args`에 포함
   - `main.py`에서 팩토리를 통해 provider 인스턴스 생성

**참조 코드**: 기존 `config_manager.py`의 `load_config_and_args()`

---

### 마일스톤 5: OpenAI Fallback Provider [선택]

**목표**: OpenAI를 LLM/TTS 폴백으로 제공한다.

**산출물**:
- `src/voice_assistant/providers/openai_llm_provider.py`
- `src/voice_assistant/providers/openai_tts_provider.py`

**구현 내용**:

1. OpenAI LLM Provider
   - `openai.OpenAI()` 클라이언트
   - `client.chat.completions.create(stream=True)` 스트리밍
   - Claude Provider와 동일한 인터페이스 (`chat_stream`, `reset_history`)

2. OpenAI TTS Provider
   - `openai.OpenAI()` 클라이언트
   - TTS API 스트리밍 응답
   - Supertonic Provider와 동일한 인터페이스 (`speak`, `stop`, `clear_queue`)

3. 팩토리 등록
   - `factory.py`에 OpenAI provider 등록
   - 폴백 체인: Claude -> OpenAI -> Ollama (LLM)
   - 폴백 체인: Supertonic -> OpenAI TTS (TTS)

---

### 마일스톤 6: .env.example 및 문서화 [보통 우선순위]

**목표**: 새 사용자가 빠르게 설정할 수 있는 템플릿을 제공한다.

**산출물**: `.env.example`

**구현 내용**:

1. `.env.example` 생성
   - 필수 키: `ANTHROPIC_API_KEY`
   - 선택 키: `OPENAI_API_KEY`, `OLLAMA_HOST`
   - 각 키에 대한 설명 주석

2. `.gitignore` 확인
   - `.env`가 `.gitignore`에 포함되어 있는지 확인
   - 없으면 추가

## 3. 기술적 접근 방식

### 3.1 아키텍처 설계 방향

```
VoiceAssistant (기존 코드 변경 최소화)
    |
    +-- LLMProvider (ABC from SPEC-PROVIDER-001)
    |       |-- ClaudeProvider      [신규, 마일스톤 1]
    |       |-- OpenAILLMProvider   [신규, 마일스톤 5]
    |       +-- OllamaProvider      [기존 LLMHandler 래핑]
    |
    +-- TTSProvider (ABC from SPEC-PROVIDER-001)
    |       |-- SupertonicProvider  [신규, 마일스톤 2]
    |       |-- OpenAITTSProvider   [신규, 마일스톤 5]
    |       +-- PiperProvider       [기존 Synthesizer 래핑]
    |
    +-- Transcriber (기존 유지, 설정만 변경)
```

### 3.2 기존 코드와의 호환성 전략

- `VoiceAssistant.__init__()`: `LLMHandler`와 `Synthesizer` 대신 팩토리에서 생성된 Provider를 주입
- `VoiceAssistant._handle_conversation()`: `self.llm.chat_stream()`과 `self.tts.speak()` 인터페이스 유지
- Provider 인터페이스가 기존 클래스의 public 메서드와 동일하게 설계되므로, `voice_assistant.py` 변경 최소화

### 3.3 스트리밍 파이프라인

```
사용자 음성 -> [STT: faster-whisper (ko)] -> 한국어 텍스트
    -> [LLM: Claude Sonnet] -> 토큰 스트리밍
    -> [문장 버퍼링] -> 완성된 문장
    -> [TTS: Supertonic] -> 큐에 추가
    -> [오디오 워커] -> sounddevice 출력
```

### 3.4 폴백 전략

```
Claude API 호출 시도
    |-- 성공: 정상 스트리밍
    |-- 실패 (네트워크/인증):
        |-- OpenAI 사용 가능? -> OpenAI로 전환
        |-- Ollama 사용 가능? -> Ollama로 전환
        |-- 모두 실패: 에러 메시지 음성 출력
```

## 4. 리스크 및 대응 계획

| 리스크 | 발생 가능성 | 영향도 | 대응 계획 |
|--------|-----------|--------|----------|
| Supertonic 한국어 음질 부족 | 중간 | 높음 | 다른 음성 스타일 시도, OpenAI TTS 폴백 |
| Claude API 지연 시간 | 낮음 | 중간 | 스트리밍으로 첫 응답 시간 최소화 |
| faster-whisper 한국어 정확도 | 중간 | 높음 | 임계값 튜닝, `medium` 모델 대안 |
| Supertonic API 변경 | 낮음 | 중간 | 버전 고정, 래퍼 패턴으로 격리 |
| API 비용 누적 | 중간 | 중간 | 토큰 사용량 로깅, max_tokens 제한 |

## 5. 변경 영향 분석

### 5.1 신규 파일

| 파일 | 설명 |
|------|------|
| `src/voice_assistant/providers/claude_provider.py` | Claude LLM Provider |
| `src/voice_assistant/providers/supertonic_provider.py` | Supertonic TTS Provider |
| `src/voice_assistant/providers/openai_llm_provider.py` | OpenAI LLM Provider (선택) |
| `src/voice_assistant/providers/openai_tts_provider.py` | OpenAI TTS Provider (선택) |
| `.env.example` | 환경변수 템플릿 |

### 5.2 변경 파일

| 파일 | 변경 사항 |
|------|----------|
| `config.ini` | provider 선택 필드, 한국어 설정, 시스템 프롬프트 |
| `src/voice_assistant/config_manager.py` | 새 argparse 인수, .env 로드, 조건부 Ollama |
| `src/voice_assistant/transcriber.py` | language 파라미터 변경 (en -> ko) |
| `src/voice_assistant/providers/factory.py` | 새 provider 등록 |
| `requirements.txt` 또는 `pyproject.toml` | anthropic, supertonic, openai 추가 |

### 5.3 변경하지 않는 파일

| 파일 | 이유 |
|------|------|
| `src/voice_assistant/voice_assistant.py` | Provider 인터페이스 호환으로 변경 불필요 |
| `src/voice_assistant/audio_input.py` | 오디오 입력 로직 변경 없음 |
| `src/voice_assistant/audio_utils.py` | 공통 유틸리티 변경 최소화 |

## 6. 구현 순서 요약

```
SPEC-PROVIDER-001 완료 (의존성)
    |
    v
[마일스톤 1] Claude Provider  ----+
[마일스톤 2] Supertonic Provider --+-- 병렬 가능
[마일스톤 3] 한국어 STT 설정 -----+
    |
    v
[마일스톤 4] 설정 통합 (config.ini + config_manager.py)
    |
    v
[마일스톤 5] OpenAI Fallback (선택)
    |
    v
[마일스톤 6] .env.example 및 문서화
```
