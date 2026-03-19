---
id: SPEC-PROVIDER-001
version: "1.0.0"
status: draft
created: "2026-03-19"
updated: "2026-03-19"
author: toby
priority: high
issue_number: 0
tags: [provider, abstraction, llm, tts, stt, config]
---

# SPEC-PROVIDER-001: LLM, TTS, STT Provider 추상화 레이어

## 1. 개요

현재 ai-speaker 프로젝트는 LLM(Ollama), TTS(Piper), STT(faster-whisper)가 각각 구체적인 구현체에 하드코딩되어 있다. 이 SPEC은 세 가지 AI 제공자(LLM, TTS, STT)에 대한 추상 베이스 클래스(ABC)와 팩토리 패턴을 도입하여, 설정만으로 제공자를 교체할 수 있는 플러거블 아키텍처를 구축한다. 또한 `.env` 파일을 통한 API 키 관리와 python-dotenv 통합을 포함한다.

## 2. 환경 (Environment)

### 2.1 현재 시스템 구조

| 구성 요소 | 현재 구현체 | 파일 위치 |
|-----------|------------|----------|
| LLM | Ollama (ollama 패키지 직접 사용) | `src/voice_assistant/llm_handler.py` |
| TTS | Piper TTS (ONNX 모델) | `src/voice_assistant/synthesizer.py` |
| STT | faster-whisper (WhisperModel) | `src/voice_assistant/transcriber.py` |
| 설정 | config.ini + argparse | `src/voice_assistant/config_manager.py` |
| 오케스트레이션 | VoiceAssistant 클래스 | `src/voice_assistant/voice_assistant.py` |

### 2.2 목표 Provider 구성

| 카테고리 | 기본(Default) Provider | 대체(Alternative) Provider |
|---------|----------------------|--------------------------|
| LLM | Claude Sonnet API (Anthropic) | OpenAI GPT API |
| TTS | Supertonic (on-device ONNX, 한국어) | Supertone Play API, OpenAI TTS |
| STT | faster-whisper (로컬) | OpenAI Whisper API |

### 2.3 기술 스택

- Python 3.9+ (pyproject.toml 기준 하한)
- 패키지 관리: setuptools (기존 pyproject.toml 유지)
- 설정 파일: config.ini (기존) + .env (신규, API 키 전용)
- 신규 의존성: python-dotenv, anthropic (Claude API)

## 3. 가정 (Assumptions)

- A1: 기존 Ollama, Piper, faster-whisper 코드는 수정 없이 래핑(wrapping)하여 레거시 Provider로 동작시킨다.
- A2: 모든 Provider는 동기(synchronous) 또는 스트리밍(streaming) 인터페이스를 지원해야 한다. LLM은 `chat_stream()` 제너레이터 패턴을 유지한다.
- A3: `.env` 파일은 git에 커밋되지 않으며, `.env.example` 템플릿만 제공한다.
- A4: 한 번에 하나의 Provider만 활성화된다 (런타임 핫스왑은 향후 고려 사항).
- A5: TTS Provider는 기존 `threading.Event` 기반 인터럽트 메커니즘과 호환되어야 한다.
- A6: STT Provider는 `numpy.ndarray` (float32) 오디오 입력을 받아 문자열을 반환하는 인터페이스를 유지한다.

## 4. 요구사항 (Requirements)

### 4.1 보편적 요구사항 (Ubiquitous)

- **[REQ-U-001]** 시스템은 LLM, TTS, STT에 대해 추상 베이스 클래스(ABC)를 통한 플러거블 Provider를 **항상** 지원해야 한다.
- **[REQ-U-002]** 시스템은 python-dotenv를 사용하여 `.env` 파일에서 API 키를 **항상** 로드해야 한다.
- **[REQ-U-003]** 시스템은 모든 Provider 초기화 및 오류 상황을 logging 모듈을 통해 **항상** 기록해야 한다.
- **[REQ-U-004]** 시스템은 기존 config.ini 기반 설정과 **항상** 하위 호환성을 유지해야 한다.

### 4.2 이벤트 기반 요구사항 (Event-Driven)

- **[REQ-E-001]** **WHEN** config.ini에 `llm_provider`, `tts_provider`, `stt_provider` 값이 지정되면, **THEN** 시스템은 해당 Provider 클래스를 인스턴스화해야 한다.
- **[REQ-E-002]** **WHEN** 클라우드 Provider에 필요한 API 키가 `.env` 파일에 없으면, **THEN** 시스템은 명확한 에러 로그를 남기고 로컬 Provider로 폴백해야 한다.
- **[REQ-E-003]** **WHEN** Provider 팩토리에 알 수 없는 Provider 이름이 전달되면, **THEN** 시스템은 `ValueError`를 발생시키고 사용 가능한 Provider 목록을 에러 메시지에 포함해야 한다.
- **[REQ-E-004]** **WHEN** Provider 초기화 중 예외가 발생하면, **THEN** 시스템은 에러를 로깅하고 해당 카테고리의 기본 Provider로 폴백을 시도해야 한다.

### 4.3 상태 기반 요구사항 (State-Driven)

- **[REQ-S-001]** **IF** 시스템이 실행 중이면, **THEN** Provider 교체는 애플리케이션 재시작을 요구한다 (런타임 핫스왑은 향후 고려 사항).
- **[REQ-S-002]** **IF** LLM Provider가 스트리밍 모드로 동작 중이면, **THEN** `chat_stream()` 메서드는 토큰 단위의 제너레이터를 반환해야 한다.
- **[REQ-S-003]** **IF** TTS Provider가 음성 합성 중이면, **THEN** `interrupt_event`를 통한 즉시 중단이 가능해야 한다.

### 4.4 선택적 요구사항 (Optional)

- **[REQ-O-001]** **가능하면** 사용자 정의 Provider를 Python entry_points를 통해 로딩하는 기능을 제공한다.
- **[REQ-O-002]** **가능하면** Provider 상태 모니터링을 위한 health check 인터페이스를 제공한다.

### 4.5 금지 행위 요구사항 (Unwanted Behavior)

- **[REQ-N-001]** 시스템은 오케스트레이션 레이어(`voice_assistant.py`)에 특정 Provider 구현을 하드코딩**하지 않아야 한다**.
- **[REQ-N-002]** 시스템은 API 키를 config.ini 또는 소스 코드에 저장**하지 않아야 한다**.
- **[REQ-N-003]** 시스템은 `.env` 파일을 버전 관리 시스템에 커밋**하지 않아야 한다**.
- **[REQ-N-004]** Provider 추상화 도입으로 인해 기존 Ollama/Piper/Whisper 기능이 동작 불능 상태가 되어서는 **안 된다**.

## 5. 명세 (Specifications)

### 5.1 Provider 추상 베이스 클래스

#### 5.1.1 LLMProvider ABC

```
클래스: LLMProvider(ABC)
위치: src/voice_assistant/providers/base.py

메서드:
  - chat_stream(user_text: str) -> Generator[str | None, None, None]
    설명: 사용자 입력에 대한 LLM 응답을 토큰 단위로 스트리밍
  - reset_history() -> None
    설명: 대화 히스토리 초기화
  - close() -> None
    설명: 리소스 정리

속성:
  - system_prompt: str (시스템 프롬프트)
  - max_history_messages: int (최대 히스토리 메시지 수)
```

#### 5.1.2 TTSProvider ABC

```
클래스: TTSProvider(ABC)
위치: src/voice_assistant/providers/base.py

메서드:
  - speak(text: str) -> None
    설명: 텍스트를 음성으로 변환하여 큐에 추가
  - stop() -> None
    설명: 음성 합성 중단 및 리소스 정리
  - clear_queue() -> None
    설명: 대기 중인 음성 큐 초기화
  - wait_until_done() -> None
    설명: 현재 큐의 모든 음성이 재생 완료될 때까지 대기

속성:
  - is_speaking: bool (현재 음성 출력 중 여부)
  - has_failed: bool (치명적 오류 발생 여부)
  - interrupt_event: threading.Event (외부 인터럽트 이벤트)
```

#### 5.1.3 STTProvider ABC

```
클래스: STTProvider(ABC)
위치: src/voice_assistant/providers/base.py

메서드:
  - transcribe(audio_np: NDArray[np.float32]) -> str
    설명: 오디오 numpy 배열을 텍스트로 변환
  - close() -> None
    설명: 모델 리소스 정리

속성:
  - language: str (인식 대상 언어, 기본값: "ko")
```

### 5.2 Provider 팩토리

```
클래스: ProviderFactory
위치: src/voice_assistant/providers/factory.py

정적 메서드:
  - create_llm(provider_name: str, config: Namespace) -> LLMProvider
  - create_tts(provider_name: str, config: Namespace, interrupt_event: Event) -> TTSProvider
  - create_stt(provider_name: str, config: Namespace) -> STTProvider

레지스트리:
  - LLM_PROVIDERS: dict[str, type[LLMProvider]]
  - TTS_PROVIDERS: dict[str, type[TTSProvider]]
  - STT_PROVIDERS: dict[str, type[STTProvider]]
```

### 5.3 레거시 Provider 래퍼

| 래퍼 클래스 | 래핑 대상 | 파일 |
|------------|----------|------|
| `OllamaProvider(LLMProvider)` | 기존 `LLMHandler` | `providers/ollama_provider.py` |
| `PiperProvider(TTSProvider)` | 기존 `Synthesizer` | `providers/piper_provider.py` |
| `WhisperProvider(STTProvider)` | 기존 `Transcriber` | `providers/whisper_provider.py` |

### 5.4 설정 확장

config.ini에 `[Providers]` 섹션 추가:

```ini
[Providers]
llm_provider = ollama        # ollama | claude | openai
tts_provider = piper         # piper | supertonic | openai
stt_provider = whisper       # whisper | openai
default_language = ko        # 기본 언어
```

`.env` 파일 구조:

```
# AI Provider API Keys
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
SUPERTONE_API_KEY=
```

### 5.5 디렉토리 구조

```
src/voice_assistant/
  providers/
    __init__.py          # Provider 레지스트리 및 공개 API
    base.py              # ABC 정의 (LLMProvider, TTSProvider, STTProvider)
    factory.py           # ProviderFactory 클래스
    ollama_provider.py   # 기존 LLMHandler 래퍼
    piper_provider.py    # 기존 Synthesizer 래퍼
    whisper_provider.py  # 기존 Transcriber 래퍼
```

## 6. 제약사항 (Constraints)

- **C-001**: 기존 테스트 스위트는 Provider 추상화 도입 후에도 통과해야 한다.
- **C-002**: 신규 의존성(python-dotenv)만 추가하고, 기존 의존성은 제거하지 않는다.
- **C-003**: Provider ABC는 기존 모듈(`llm_handler.py`, `synthesizer.py`, `transcriber.py`)의 공개 인터페이스를 유지하여 점진적 마이그레이션을 지원한다.
- **C-004**: `.env.example` 템플릿 파일은 반드시 저장소에 포함한다.

## 7. 추적성 (Traceability)

| 요구사항 ID | 구현 대상 | 검증 방법 |
|------------|----------|----------|
| REQ-U-001 | `providers/base.py` ABC 정의 | 단위 테스트: ABC 상속 검증 |
| REQ-U-002 | `config_manager.py` dotenv 통합 | 통합 테스트: .env 로딩 검증 |
| REQ-E-001 | `providers/factory.py` 팩토리 | 단위 테스트: Provider 인스턴스화 |
| REQ-E-002 | `providers/factory.py` 폴백 | 통합 테스트: API 키 미설정 시 폴백 |
| REQ-E-003 | `providers/factory.py` 오류 처리 | 단위 테스트: 잘못된 Provider명 |
| REQ-N-001 | `voice_assistant.py` 리팩토링 | 코드 리뷰: 하드코딩 제거 확인 |
| REQ-N-002 | `.gitignore`, 코드 리뷰 | 보안 검사: API 키 노출 여부 |
