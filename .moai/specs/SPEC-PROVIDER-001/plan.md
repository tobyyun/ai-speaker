---
id: SPEC-PROVIDER-001
type: plan
version: "1.0.0"
status: draft
created: "2026-03-19"
updated: "2026-03-19"
author: toby
tags: [provider, abstraction, llm, tts, stt, config]
---

# SPEC-PROVIDER-001: 구현 계획

## 1. 마일스톤 개요

### 1차 목표 (Primary Goal): Provider 추상화 프레임워크 구축

Provider ABC 정의, 팩토리 패턴 구현, .env 통합, 레거시 래퍼 생성

### 2차 목표 (Secondary Goal): 오케스트레이션 레이어 리팩토링

VoiceAssistant가 Provider 팩토리를 통해 동작하도록 전환

### 3차 목표 (Final Goal): 검증 및 하위 호환성 확인

기존 테스트 통과, 신규 단위 테스트 추가, .env.example 제공

---

## 2. 상세 구현 계획

### 마일스톤 1: Provider ABC 및 팩토리 (우선순위: 높음)

#### 태스크 1.1: `providers/` 패키지 생성

- `src/voice_assistant/providers/__init__.py` 생성
  - Provider 클래스와 팩토리를 공개 API로 노출
  - `__all__` 리스트에 ABC와 팩토리 포함

#### 태스크 1.2: `providers/base.py` - 추상 베이스 클래스 정의

- `LLMProvider(ABC)` 정의
  - `__init__(self, config: Namespace)`: 설정 주입
  - `chat_stream(self, user_text: str) -> Generator[str | None, None, None]`: 스트리밍 응답
  - `reset_history(self) -> None`: 히스토리 초기화
  - `close(self) -> None`: 리소스 정리
- `TTSProvider(ABC)` 정의
  - `__init__(self, config: Namespace, interrupt_event: threading.Event)`: 설정 및 인터럽트 이벤트 주입
  - `speak(self, text: str) -> None`: 음성 합성 큐잉
  - `stop(self) -> None`: 리소스 정리
  - `clear_queue(self) -> None`: 큐 초기화
  - `wait_until_done(self) -> None`: 재생 완료 대기
  - `is_speaking` / `has_failed` 프로퍼티
- `STTProvider(ABC)` 정의
  - `__init__(self, config: Namespace)`: 설정 주입
  - `transcribe(self, audio_np: NDArray[np.float32]) -> str`: 음성 인식
  - `close(self) -> None`: 리소스 정리

#### 태스크 1.3: `providers/factory.py` - Provider 팩토리

- `ProviderFactory` 클래스 구현
  - 내부 레지스트리: `_LLM_REGISTRY`, `_TTS_REGISTRY`, `_STT_REGISTRY`
  - `create_llm(provider_name, config) -> LLMProvider`
  - `create_tts(provider_name, config, interrupt_event) -> TTSProvider`
  - `create_stt(provider_name, config) -> STTProvider`
  - `register_provider(category, name, cls)` 정적 메서드 (확장용)
- 오류 처리:
  - 알 수 없는 Provider명 -> `ValueError` + 사용 가능 목록
  - Provider 초기화 실패 -> 로깅 후 기본 Provider 폴백
  - API 키 누락 -> 명확한 에러 메시지 + 로컬 폴백

### 마일스톤 2: 레거시 Provider 래퍼 (우선순위: 높음)

#### 태스크 2.1: `providers/ollama_provider.py`

- `OllamaProvider(LLMProvider)` 클래스
  - 기존 `LLMHandler` 로직을 내부적으로 활용
  - `ollama.Client` 생성을 `__init__`에서 처리
  - `chat_stream()`: 기존 `LLMHandler.chat_stream()` 로직 래핑
  - `reset_history()`: 기존 `LLMHandler.reset_history()` 위임
  - `close()`: 리소스 정리
- 호환성: 기존 config.ini의 `ollama_model`, `ollama_host` 설정 그대로 사용

#### 태스크 2.2: `providers/piper_provider.py`

- `PiperProvider(TTSProvider)` 클래스
  - 기존 `Synthesizer` 로직을 내부적으로 활용
  - `__init__`: Piper 모델 로딩, 워커 스레드 시작
  - `speak()`: 기존 `Synthesizer.speak()` 위임
  - `stop()`: 기존 `Synthesizer.stop()` 위임
  - `clear_queue()`: 기존 `Synthesizer.clear_queue()` 위임
  - `wait_until_done()`: `self.queue.join()` 래핑
- 호환성: 기존 `piper_model_path`, `piper_output_device_index` 설정 유지

#### 태스크 2.3: `providers/whisper_provider.py`

- `WhisperProvider(STTProvider)` 클래스
  - 기존 `Transcriber` 로직을 내부적으로 활용
  - `__init__`: WhisperModel 초기화, CUDA 자동 감지
  - `transcribe()`: 기존 `Transcriber.transcribe()` 위임 (타임아웃 포함)
  - `close()`: 기존 `Transcriber.close()` 위임
- 호환성: 기존 `whisper_model`, `whisper_device`, `whisper_compute_type` 설정 유지

### 마일스톤 3: 설정 시스템 확장 (우선순위: 높음)

#### 태스크 3.1: python-dotenv 통합

- `config_manager.py` 수정:
  - 파일 상단에서 `from dotenv import load_dotenv` 및 `load_dotenv()` 호출
  - `os.environ.get()` 을 통해 API 키 접근
  - `.env` 파일이 없으면 경고 로그만 출력 (오류 아님)

#### 태스크 3.2: config.ini에 `[Providers]` 섹션 추가

- `config_manager.py`의 `load_config_and_args()`에 Provider 설정 파싱 추가:
  - `llm_provider`: 기본값 `"ollama"`
  - `tts_provider`: 기본값 `"piper"`
  - `stt_provider`: 기본값 `"whisper"`
  - `default_language`: 기본값 `"ko"`
- argparse에 `--llm-provider`, `--tts-provider`, `--stt-provider` 인자 추가
- `DEFAULT_SETTINGS` 딕셔너리에 Provider 관련 기본값 추가

#### 태스크 3.3: `.env.example` 생성

- 프로젝트 루트에 `.env.example` 파일 생성:
  ```
  # AI Provider API Keys
  # Anthropic Claude API (LLM)
  ANTHROPIC_API_KEY=your_anthropic_api_key_here

  # OpenAI API (LLM/TTS/STT fallback)
  OPENAI_API_KEY=your_openai_api_key_here

  # Supertone API (TTS)
  SUPERTONE_API_KEY=your_supertone_api_key_here
  ```
- `.gitignore`에 `.env` 추가 확인

### 마일스톤 4: 오케스트레이션 리팩토링 (우선순위: 중간)

#### 태스크 4.1: `voice_assistant.py` Provider 팩토리 통합

- `VoiceAssistant.__init__()` 수정:
  - 기존: 직접 `Transcriber(args)`, `Synthesizer(args, ...)`, `LLMHandler(client, args)` 생성
  - 변경: `ProviderFactory.create_stt()`, `ProviderFactory.create_tts()`, `ProviderFactory.create_llm()` 사용
- `_handle_conversation()` 수정:
  - `self.tts.speak()` -> Provider 인터페이스 메서드 호출 (동일 시그니처)
  - `self.tts.queue.join()` -> `self.tts.wait_until_done()`
  - `self.llm.chat_stream()` -> Provider 인터페이스 메서드 호출 (동일 시그니처)
- `cleanup()` 수정:
  - 각 Provider의 `close()` / `stop()` 호출

#### 태스크 4.2: Ollama Client 의존성 제거

- `config_manager.py`에서 `get_ollama_client()` 함수를 Provider 내부로 이동
  - `ollama` import를 `config_manager.py`에서 제거
  - `OllamaProvider.__init__()` 내부에서 Ollama 클라이언트 생성
- `voice_assistant.py`에서 `client` 파라미터 제거
  - `__init__(self, args)` 로 시그니처 단순화

### 마일스톤 5: pyproject.toml 업데이트 (우선순위: 중간)

#### 태스크 5.1: 의존성 추가

- `dependencies`에 추가:
  - `python-dotenv>=1.0.0`
- `[project.optional-dependencies]`에 Provider별 그룹 추가:
  ```toml
  [project.optional-dependencies]
  claude = ["anthropic>=0.40.0"]
  openai = ["openai>=1.50.0"]
  all-providers = ["anthropic>=0.40.0", "openai>=1.50.0"]
  ```
- 기존 의존성(`ollama`, `piper-tts`, `faster-whisper` 등)은 그대로 유지

#### 태스크 5.2: 프로젝트 메타데이터 업데이트

- `name`을 `"ai-speaker"`로 변경 (포크 프로젝트 반영)
- `description` 업데이트: 멀티 프로바이더 지원 언급

---

## 3. 기술적 접근 방식

### 3.1 설계 패턴

- **Strategy Pattern**: 각 Provider ABC가 전략 인터페이스, 구체적 Provider가 전략 구현
- **Factory Pattern**: `ProviderFactory`가 config 기반으로 적절한 Provider 인스턴스 생성
- **Adapter Pattern**: 레거시 래퍼(`OllamaProvider` 등)가 기존 코드를 새 인터페이스에 적응

### 3.2 폴백 전략

```
Provider 로딩 순서:
1. config.ini에서 지정된 Provider 이름 확인
2. .env에서 필요한 API 키 존재 여부 확인
3. API 키 존재 -> 지정된 Provider 초기화 시도
4. API 키 부재 또는 초기화 실패 -> 경고 로그 출력
5. 해당 카테고리의 기본 로컬 Provider로 폴백
   - LLM 기본: ollama
   - TTS 기본: piper
   - STT 기본: whisper
```

### 3.3 하위 호환성 보장

- 기존 `LLMHandler`, `Synthesizer`, `Transcriber` 클래스는 삭제하지 않음
- Provider 래퍼가 기존 클래스를 내부적으로 사용 (컴포지션)
- config.ini에 `[Providers]` 섹션이 없으면 기존 기본값(`ollama`, `piper`, `whisper`) 사용
- `.env` 파일이 없어도 경고만 출력하고 정상 동작

---

## 4. 아키텍처 설계 방향

### 4.1 모듈 의존성 흐름

```
voice_assistant.py (오케스트레이션)
  |
  +-> providers/factory.py (팩토리)
        |
        +-> providers/base.py (ABC)
        |
        +-> providers/ollama_provider.py -> llm_handler.py (기존 코드)
        +-> providers/piper_provider.py  -> synthesizer.py  (기존 코드)
        +-> providers/whisper_provider.py -> transcriber.py (기존 코드)
  |
  +-> config_manager.py (설정 + dotenv)
        |
        +-> .env (API 키)
        +-> config.ini (일반 설정 + Provider 선택)
```

### 4.2 인터페이스 계약

모든 Provider는 다음 계약을 준수:

1. **초기화**: `config: Namespace`를 받아 필요한 리소스를 로드
2. **오류 처리**: 초기화 실패 시 명확한 예외 발생 (팩토리가 처리)
3. **리소스 정리**: `close()` 또는 `stop()` 호출 시 모든 리소스 해제
4. **스레드 안전성**: TTS Provider는 자체 워커 스레드 관리

---

## 5. 리스크 및 대응 계획

| 리스크 | 영향도 | 발생 가능성 | 대응 방안 |
|-------|-------|-----------|---------|
| 기존 테스트 깨짐 | 높음 | 중간 | 래퍼 패턴으로 기존 인터페이스 100% 유지 |
| TTS 스레딩 호환성 문제 | 높음 | 낮음 | TTSProvider ABC에 `interrupt_event` 계약 명시 |
| .env 파일 누락으로 클라우드 Provider 실패 | 중간 | 높음 | 자동 폴백 + 명확한 에러 메시지 |
| Ollama 없이 기본 설정으로 실행 시 실패 | 중간 | 중간 | Provider 미설정 시 기본값을 로컬 Provider로 유지 |
| 기존 코드와 신규 Provider 간 시그니처 불일치 | 중간 | 낮음 | ABC에 기존 시그니처를 반영하여 설계 |

---

## 6. 파일 변경 요약

| 파일 | 변경 유형 | 설명 |
|-----|---------|------|
| `src/voice_assistant/providers/__init__.py` | 신규 | 패키지 초기화, 공개 API |
| `src/voice_assistant/providers/base.py` | 신규 | ABC 정의 |
| `src/voice_assistant/providers/factory.py` | 신규 | 팩토리 클래스 |
| `src/voice_assistant/providers/ollama_provider.py` | 신규 | Ollama 래퍼 |
| `src/voice_assistant/providers/piper_provider.py` | 신규 | Piper 래퍼 |
| `src/voice_assistant/providers/whisper_provider.py` | 신규 | Whisper 래퍼 |
| `src/voice_assistant/config_manager.py` | 수정 | dotenv 통합, Provider 설정 파싱 |
| `src/voice_assistant/voice_assistant.py` | 수정 | 팩토리 통합, 하드코딩 제거 |
| `src/voice_assistant/audio_utils.py` | 수정 | DEFAULT_SETTINGS에 Provider 기본값 추가 |
| `config.ini` | 수정 | [Providers] 섹션 추가 |
| `pyproject.toml` | 수정 | python-dotenv 추가, optional deps |
| `.env.example` | 신규 | API 키 템플릿 |
| `.gitignore` | 수정 | .env 추가 |
