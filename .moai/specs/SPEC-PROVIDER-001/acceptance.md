---
id: SPEC-PROVIDER-001
type: acceptance
version: "1.0.0"
status: draft
created: "2026-03-19"
updated: "2026-03-19"
author: toby
tags: [provider, abstraction, llm, tts, stt, config]
---

# SPEC-PROVIDER-001: 인수 기준

## 1. Provider 팩토리 동작 검증

### 시나리오 1.1: config.ini에서 Provider 로딩 (REQ-E-001)

```gherkin
Given config.ini의 [Providers] 섹션에 llm_provider = ollama 가 설정되어 있고
  And config.ini의 [Providers] 섹션에 tts_provider = piper 가 설정되어 있고
  And config.ini의 [Providers] 섹션에 stt_provider = whisper 가 설정되어 있을 때
When ProviderFactory를 통해 각 Provider를 생성하면
Then LLMProvider 인스턴스가 OllamaProvider 타입이어야 하고
  And TTSProvider 인스턴스가 PiperProvider 타입이어야 하고
  And STTProvider 인스턴스가 WhisperProvider 타입이어야 한다
```

### 시나리오 1.2: [Providers] 섹션 미설정 시 기본값 (REQ-U-004)

```gherkin
Given config.ini에 [Providers] 섹션이 존재하지 않을 때
When ProviderFactory를 통해 각 Provider를 생성하면
Then LLM Provider는 기본값 "ollama"로 OllamaProvider가 생성되어야 하고
  And TTS Provider는 기본값 "piper"로 PiperProvider가 생성되어야 하고
  And STT Provider는 기본값 "whisper"로 WhisperProvider가 생성되어야 한다
```

### 시나리오 1.3: 잘못된 Provider 이름 (REQ-E-003)

```gherkin
Given config.ini에 llm_provider = nonexistent_provider 가 설정되어 있을 때
When ProviderFactory.create_llm()을 호출하면
Then ValueError가 발생해야 하고
  And 에러 메시지에 사용 가능한 Provider 목록("ollama")이 포함되어야 한다
```

### 시나리오 1.4: Provider 초기화 실패 시 폴백 (REQ-E-004)

```gherkin
Given config.ini에 llm_provider = claude 가 설정되어 있고
  And Anthropic API 서버에 연결할 수 없을 때
When ProviderFactory.create_llm()을 호출하면
Then 에러가 로깅되어야 하고
  And 기본 Provider인 OllamaProvider로 폴백되어야 한다
```

---

## 2. .env API 키 로딩 검증

### 시나리오 2.1: .env에서 API 키 정상 로딩 (REQ-U-002)

```gherkin
Given 프로젝트 루트에 .env 파일이 존재하고
  And .env 파일에 ANTHROPIC_API_KEY=sk-ant-test123 이 설정되어 있을 때
When config_manager.load_config_and_args()가 실행되면
Then os.environ["ANTHROPIC_API_KEY"] 값이 "sk-ant-test123"이어야 한다
```

### 시나리오 2.2: .env 파일 부재 시 동작 (REQ-U-002)

```gherkin
Given 프로젝트 루트에 .env 파일이 존재하지 않을 때
When config_manager.load_config_and_args()가 실행되면
Then 경고 로그가 출력되어야 하고
  And 애플리케이션은 정상적으로 계속 실행되어야 한다
```

### 시나리오 2.3: 클라우드 Provider에 API 키 누락 (REQ-E-002)

```gherkin
Given config.ini에 llm_provider = claude 가 설정되어 있고
  And .env 파일에 ANTHROPIC_API_KEY 가 비어있거나 존재하지 않을 때
When ProviderFactory.create_llm("claude", config)을 호출하면
Then "ANTHROPIC_API_KEY가 설정되지 않았습니다" 형태의 에러 로그가 출력되어야 하고
  And 기본 로컬 Provider(OllamaProvider)로 자동 폴백되어야 한다
```

---

## 3. Provider ABC 인터페이스 검증

### 시나리오 3.1: LLMProvider 스트리밍 응답 (REQ-S-002)

```gherkin
Given OllamaProvider가 정상적으로 초기화되어 있을 때
When chat_stream("안녕하세요")를 호출하면
Then 문자열 토큰을 yield하는 제너레이터가 반환되어야 하고
  And 각 토큰은 str 또는 None 타입이어야 한다
```

### 시나리오 3.2: LLMProvider 히스토리 초기화 (REQ-U-001)

```gherkin
Given OllamaProvider에 이전 대화 히스토리가 존재할 때
When reset_history()를 호출하면
Then 대화 히스토리가 시스템 프롬프트만 남기고 초기화되어야 한다
```

### 시나리오 3.3: TTSProvider 인터럽트 (REQ-S-003)

```gherkin
Given PiperProvider가 텍스트 음성 합성 중이고
  And is_speaking 속성이 True 일 때
When interrupt_event.set()이 호출되면
Then 현재 음성 합성이 즉시 중단되어야 하고
  And 큐에 남은 텍스트는 처리되지 않아야 한다
```

### 시나리오 3.4: STTProvider 음성 인식 (REQ-U-001)

```gherkin
Given WhisperProvider가 정상적으로 초기화되어 있고
  And 16kHz float32 numpy 배열 오디오 데이터가 준비되어 있을 때
When transcribe(audio_np)를 호출하면
Then 인식된 텍스트 문자열이 반환되어야 한다
```

### 시나리오 3.5: STTProvider 빈 오디오 처리

```gherkin
Given WhisperProvider가 정상적으로 초기화되어 있고
  And 무음(silence)인 numpy 배열이 준비되어 있을 때
When transcribe(audio_np)를 호출하면
Then 빈 문자열("")이 반환되어야 한다
```

---

## 4. 하위 호환성 검증

### 시나리오 4.1: 기존 설정으로 정상 동작 (REQ-U-004, REQ-N-004)

```gherkin
Given 기존 config.ini에 [Providers] 섹션이 없고
  And .env 파일이 존재하지 않으며
  And Ollama 서버가 실행 중일 때
When VoiceAssistant를 기존 방식으로 초기화하면
Then 시스템이 정상적으로 시작되어야 하고
  And 기존과 동일하게 Ollama + Piper + Whisper 조합으로 동작해야 한다
```

### 시나리오 4.2: 기존 테스트 스위트 통과

```gherkin
Given Provider 추상화 레이어가 적용된 후
When 기존 테스트 스위트를 실행하면
Then 모든 기존 테스트가 통과해야 한다
```

---

## 5. 보안 검증

### 시나리오 5.1: API 키가 소스 코드에 없음 (REQ-N-002)

```gherkin
Given Provider 추상화가 구현된 후
When 전체 소스 코드를 검색하면
Then API 키 문자열이 하드코딩된 곳이 없어야 하고
  And config.ini에 API 키가 포함되어 있지 않아야 한다
```

### 시나리오 5.2: .env 파일이 git에 포함되지 않음 (REQ-N-003)

```gherkin
Given .gitignore에 .env 가 포함되어 있을 때
When git status를 실행하면
Then .env 파일이 추적 대상에 포함되지 않아야 하고
  And .env.example 파일은 추적 대상에 포함되어야 한다
```

### 시나리오 5.3: 하드코딩 제거 확인 (REQ-N-001)

```gherkin
Given Provider 리팩토링이 완료된 후
When voice_assistant.py를 검사하면
Then "ollama", "Piper", "WhisperModel" 등 특정 구현체를 직접 import하는 코드가 없어야 하고
  And Provider 인터페이스(ABC)를 통해서만 상호작용해야 한다
```

---

## 6. 엣지 케이스

### 시나리오 6.1: 모든 Provider 초기화 실패

```gherkin
Given LLM, TTS, STT 모든 Provider가 초기화에 실패할 때
When VoiceAssistant를 시작하면
Then 각 Provider별로 명확한 에러 메시지가 로깅되어야 하고
  And 시스템은 적절한 exit code와 함께 종료되어야 한다
```

### 시나리오 6.2: .env 파일에 잘못된 형식

```gherkin
Given .env 파일에 잘못된 형식(예: 키=값 없이 텍스트만)이 포함되어 있을 때
When config_manager.load_config_and_args()가 실행되면
Then python-dotenv가 파싱 가능한 항목만 로딩하고
  And 파싱 불가 항목은 무시하며 경고를 출력해야 한다
```

### 시나리오 6.3: config.ini Provider 이름에 공백/대소문자

```gherkin
Given config.ini에 llm_provider = " Claude " (공백 포함, 대문자)가 설정되어 있을 때
When ProviderFactory가 Provider를 생성하면
Then 이름이 정규화(strip + lowercase)되어 "claude" Provider가 생성되어야 한다
```

### 시나리오 6.4: 동시 TTS 중단과 새 음성 요청

```gherkin
Given PiperProvider가 음성 합성 중이고
When interrupt_event.set() 직후 즉시 speak("새로운 텍스트")가 호출되면
Then 이전 음성은 중단되어야 하고
  And 새로운 텍스트가 큐에 추가되어야 한다
```

---

## 7. 품질 게이트 기준

### 7.1 코드 품질

- Provider ABC의 모든 public 메서드에 type hint 적용
- 모든 Provider 클래스에 docstring 작성
- ruff 린팅 경고 0건
- mypy 타입 체크 통과

### 7.2 테스트 커버리지

- `providers/base.py`: ABC 인스턴스화 불가 테스트
- `providers/factory.py`: 정상/비정상 Provider 생성 테스트
- `providers/ollama_provider.py`: 기본 동작 단위 테스트
- `providers/piper_provider.py`: 기본 동작 단위 테스트
- `providers/whisper_provider.py`: 기본 동작 단위 테스트
- 전체 신규 코드 커버리지 목표: 85% 이상

### 7.3 완료 정의 (Definition of Done)

- [ ] 모든 Provider ABC가 정의되고 테스트됨
- [ ] Provider 팩토리가 config.ini 기반으로 정상 동작
- [ ] 레거시 래퍼 3종이 기존 코드를 정상적으로 래핑
- [ ] python-dotenv 통합 완료 및 .env.example 제공
- [ ] voice_assistant.py에서 하드코딩된 Provider 참조 제거
- [ ] config.ini에 [Providers] 섹션 추가
- [ ] pyproject.toml에 python-dotenv 의존성 추가
- [ ] 기존 테스트 스위트 전체 통과
- [ ] 신규 단위 테스트 85% 이상 커버리지
- [ ] .gitignore에 .env 포함 확인
- [ ] ruff 린팅 경고 0건
