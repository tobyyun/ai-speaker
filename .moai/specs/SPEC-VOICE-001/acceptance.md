---
id: SPEC-VOICE-001
type: acceptance
version: "1.0.0"
status: draft
created: "2026-03-19"
updated: "2026-03-19"
author: toby
---

# SPEC-VOICE-001 인수 기준

## 1. Claude API 스트리밍 대화 (AC-001)

### 시나리오 1.1: 기본 한국어 대화

```gherkin
Given Claude Provider가 유효한 ANTHROPIC_API_KEY로 초기화되었다
  And config.ini에 llm_provider = claude가 설정되었다
  And 한국어 시스템 프롬프트가 로드되었다
When 사용자가 "오늘 날씨 어때?"라고 질문하면
Then Claude API가 스트리밍으로 한국어 응답을 반환한다
  And 각 토큰이 순차적으로 yield된다
  And 완성된 문장이 TTS 큐에 전달된다
  And 전체 응답이 대화 히스토리에 저장된다
```

### 시나리오 1.2: 스트리밍 문장 버퍼링

```gherkin
Given Claude Provider가 정상 동작 중이다
When LLM이 "안녕하세요. 오늘 서울의 날씨는 맑습니다. 기온은 15도입니다."를 스트리밍하면
Then "안녕하세요."가 첫 번째 문장으로 TTS에 전달된다
  And "오늘 서울의 날씨는 맑습니다."가 두 번째 문장으로 TTS에 전달된다
  And "기온은 15도입니다."가 마지막 문장으로 TTS에 전달된다
  And 각 문장은 마침표(.), 물음표(?), 느낌표(!) 기준으로 분리된다
```

### 시나리오 1.3: 대화 히스토리 관리

```gherkin
Given Claude Provider가 정상 동작 중이다
  And 대화 히스토리에 10개의 메시지가 있다
When 새로운 사용자 메시지가 추가되면
Then 히스토리가 MAX_HISTORY_MESSAGES 제한 내로 pruning된다
  And 시스템 프롬프트(첫 번째 메시지)는 항상 유지된다
  And 가장 최근 메시지들이 보존된다
```

### 시나리오 1.4: Claude API max_tokens 제한

```gherkin
Given Claude Provider가 초기화되었다
When 스트리밍 요청을 보내면
Then max_tokens가 512 이하로 설정된다
  And 음성 비서에 적합한 간결한 응답이 생성된다
```

## 2. Supertonic 한국어 TTS (AC-002)

### 시나리오 2.1: 기본 한국어 음성 합성

```gherkin
Given Supertonic Provider가 auto_download=True로 초기화되었다
  And 한국어 음성 모델이 로드되었다
  And config.ini에 tts_provider = supertonic이 설정되었다
When "안녕하세요, 반갑습니다."라는 텍스트가 speak()에 전달되면
Then 텍스트가 TTS 큐에 추가된다
  And 워커 스레드가 Supertonic으로 음성을 합성한다
  And sounddevice를 통해 오디오가 출력된다
  And 출력 완료 후 is_speaking 상태가 해제된다
```

### 시나리오 2.2: 큐 기반 비동기 재생

```gherkin
Given Supertonic Provider가 정상 동작 중이다
  And 현재 첫 번째 문장을 발화 중이다
When 두 번째 문장과 세 번째 문장이 연속으로 speak()에 전달되면
Then 두 번째와 세 번째 문장이 큐에 추가된다
  And speak() 호출은 블로킹되지 않고 즉시 반환된다
  And 첫 번째 문장 완료 후 두 번째 문장이 자동 재생된다
  And 모든 문장 완료 후 is_speaking이 False가 된다
```

### 시나리오 2.3: 인터럽트 처리

```gherkin
Given Supertonic Provider가 음성을 출력 중이다
When interrupt_event가 set되면
Then 현재 재생 중인 오디오가 즉시 중단된다
  And 큐에 남은 문장들이 clear_queue()로 제거된다
```

### 시나리오 2.4: Supertonic 모델 자동 다운로드

```gherkin
Given 시스템에 Supertonic 모델이 설치되어 있지 않다
When Supertonic Provider가 auto_download=True로 초기화되면
Then 필요한 ONNX 모델이 자동으로 다운로드된다
  And 다운로드 완료 후 정상적으로 음성 합성이 가능하다
  And 다운로드 진행 상황이 로그에 기록된다
```

### 시나리오 2.5: 리소스 정리

```gherkin
Given Supertonic Provider가 동작 중이다
When stop()이 호출되면
Then 워커 스레드가 정상 종료된다(timeout 5초)
  And TTS 모델 리소스가 해제된다
  And 큐가 비워진다
```

## 3. 한국어 STT 음성 인식 (AC-003)

### 시나리오 3.1: 한국어 음성 변환

```gherkin
Given faster-whisper가 small 모델(다국어)로 로드되었다
  And language가 "ko"로 설정되었다
When 사용자가 한국어로 "지금 몇 시야?"라고 말하면
Then 음성이 한국어 텍스트 "지금 몇 시야?"로 변환된다
  And 변환 결과의 language 필드가 "ko"이다
```

### 시나리오 3.2: 한국어 인식 임계값

```gherkin
Given whisper_avg_logprob가 -1.2로 설정되었다
  And whisper_no_speech_prob가 0.7로 설정되었다
When 한국어 음성 세그먼트가 transcribe에 전달되면
Then avg_logprob > -1.2인 세그먼트만 유효한 것으로 인정된다
  And no_speech_prob < 0.7인 세그먼트만 유효한 것으로 인정된다
  And 임계값 미달 세그먼트는 로그에 기록 후 폐기된다
```

### 시나리오 3.3: 점진적 임계값 완화 (재시도)

```gherkin
Given 첫 번째 변환 시도에서 유효한 세그먼트가 없다
When 재시도 로직이 실행되면
Then 두 번째 시도에서 logprob 임계값이 -1.35, no_speech_prob이 0.8로 완화된다
  And 세 번째 시도에서 logprob 임계값이 -1.5, no_speech_prob이 0.9로 완화된다
  And 최대 3회 시도 후 원래 임계값으로 복원된다
```

## 4. Provider 폴백 (AC-004)

### 시나리오 4.1: Claude API 네트워크 에러 폴백

```gherkin
Given Claude Provider가 기본 LLM으로 설정되었다
  And OpenAI API 키가 .env에 설정되었다
When Claude API 호출 시 네트워크 에러가 발생하면
Then 에러가 로그에 기록된다
  And API 키 값은 로그에 포함되지 않는다
  And Provider 팩토리가 OpenAI Provider로 전환한다
  And 사용자에게 폴백 전환을 알리지 않고 자연스럽게 응답한다
```

### 시나리오 4.2: Claude API 인증 에러

```gherkin
Given config.ini에 llm_provider = claude가 설정되었다
  And ANTHROPIC_API_KEY가 유효하지 않다
When Claude Provider 초기화를 시도하면
Then AuthenticationError가 명확한 메시지로 로깅된다
  And API 키 전체 값은 로그에 노출되지 않는다
  And 시스템이 크래시하지 않고 폴백 provider로 시도한다
```

### 시나리오 4.3: 모든 LLM Provider 실패

```gherkin
Given Claude, OpenAI, Ollama 모두 사용 불가능하다
When LLM 호출이 필요하면
Then 에러 메시지가 로그에 기록된다
  And TTS를 통해 사용자에게 "죄송합니다, 현재 서비스를 사용할 수 없습니다."를 음성으로 안내한다
  And 시스템이 크래시하지 않고 다음 wake word를 대기한다
```

### 시나리오 4.4: API 레이트 리밋

```gherkin
Given Claude API에 레이트 리밋이 적용되었다
When chat_stream() 호출 시 RateLimitError가 발생하면
Then 지수 백오프로 최대 3회 재시도한다
  And 3회 실패 후 폴백 provider로 전환한다
```

## 5. Ollama 독립 동작 (AC-005)

### 시나리오 5.1: Ollama 없이 시스템 시작

```gherkin
Given Ollama가 시스템에 설치되어 있지 않다
  And config.ini에 llm_provider = claude가 설정되었다
  And ANTHROPIC_API_KEY가 유효하다
When 시스템이 시작되면
Then Ollama 연결을 시도하지 않는다
  And Claude Provider가 정상적으로 초기화된다
  And 에러 없이 음성 비서가 동작한다
```

### 시나리오 5.2: Ollama를 명시적으로 선택

```gherkin
Given config.ini에 llm_provider = ollama가 설정되었다
When 시스템이 시작되면
Then Ollama 연결을 시도한다
  And 연결 성공 시 기존 방식대로 동작한다
  And 연결 실패 시 명확한 에러 메시지를 출력한다
```

## 6. API 키 보안 (AC-006)

### 시나리오 6.1: .env 파일에서 키 로드

```gherkin
Given .env 파일에 ANTHROPIC_API_KEY=sk-ant-xxx가 설정되었다
When 시스템이 시작되면
Then python-dotenv를 통해 환경변수가 로드된다
  And Claude Provider가 해당 키로 초기화된다
```

### 시나리오 6.2: 로그에 키 미노출

```gherkin
Given Claude Provider가 동작 중이다
When API 에러가 발생하여 로깅될 때
Then 에러 메시지에 API 키 전체 값이 포함되지 않는다
  And "sk-ant-***" 형태로 마스킹 처리된다
  And request/response 헤더의 Authorization 값도 마스킹된다
```

### 시나리오 6.3: API 키 미설정 시 안전한 처리

```gherkin
Given .env 파일이 없거나 ANTHROPIC_API_KEY가 비어있다
When Claude Provider 초기화를 시도하면
Then "ANTHROPIC_API_KEY가 설정되지 않았습니다" 에러 메시지가 로깅된다
  And 시스템이 크래시하지 않는다
  And 폴백 provider 사용을 시도한다
```

## 7. 엣지 케이스

### 시나리오 7.1: 빈 LLM 응답

```gherkin
Given Claude Provider가 동작 중이다
When API가 빈 응답(토큰 없음)을 반환하면
Then TTS에 아무것도 전달되지 않는다
  And 에러가 로깅된다
  And 시스템이 다음 wake word 대기 상태로 복귀한다
```

### 시나리오 7.2: 매우 긴 LLM 응답

```gherkin
Given Claude Provider에 max_tokens가 512로 설정되었다
When 응답이 max_tokens 제한에 도달하면
Then 마지막 불완전한 문장 버퍼가 TTS로 전달된다
  And 대화 히스토리에 전체 응답이 저장된다
```

### 시나리오 7.3: TTS 연속 에러

```gherkin
Given Supertonic Provider가 동작 중이다
When TTS 합성 시 연속 에러가 MAX_TTS_ERRORS 횟수만큼 발생하면
Then has_failed 이벤트가 설정된다
  And 이후 speak() 호출이 무시된다
  And 에러 원인이 로그에 기록된다
```

### 시나리오 7.4: 네트워크 중간 끊김 (스트리밍 중)

```gherkin
Given Claude API 스트리밍이 진행 중이다
When 스트리밍 도중 네트워크가 끊기면
Then 이미 수신된 토큰으로 구성된 문장까지는 TTS에 전달된다
  And 에러가 로깅된다
  And 불완전한 문장 버퍼는 폐기된다
  And 사용자 메시지가 히스토리에서 롤백된다
```

### 시나리오 7.5: 한국어/영어 혼합 입력

```gherkin
Given STT가 한국어 모드로 동작 중이다
When 사용자가 "Python 코드 작성해줘"와 같이 영어가 혼합된 한국어를 말하면
Then STT가 혼합 텍스트를 정상적으로 인식한다
  And LLM에 혼합 텍스트가 전달된다
  And LLM이 한국어로 응답한다
```

## 8. 품질 게이트

### Definition of Done

- [ ] Claude Provider가 스트리밍 대화를 정상 수행한다
- [ ] Supertonic Provider가 한국어 음성을 정상 출력한다
- [ ] faster-whisper가 한국어를 정상 인식한다
- [ ] config.ini에서 provider 전환이 가능하다
- [ ] API 키가 로그에 노출되지 않는다
- [ ] Ollama 없이 시스템이 정상 시작된다
- [ ] 기존 wake word 감지 및 대화 흐름이 변경되지 않는다
- [ ] .env.example 파일이 제공된다
- [ ] 모든 새 Provider에 타입 힌트가 적용되었다
- [ ] 에러 발생 시 시스템이 크래시하지 않는다

### 검증 방법

| 검증 항목 | 방법 |
|----------|------|
| Claude 스트리밍 | 수동 테스트: 한국어 질문 -> 한국어 응답 스트리밍 확인 |
| Supertonic 음성 | 수동 테스트: 한국어 텍스트 -> 음성 출력 확인 |
| 한국어 STT | 수동 테스트: 한국어 음성 -> 텍스트 변환 확인 |
| 폴백 동작 | 수동 테스트: ANTHROPIC_API_KEY를 잘못 설정 -> 폴백 전환 확인 |
| 보안 | 로그 검사: API 키 마스킹 확인 |
| 단위 테스트 | pytest: Provider 초기화, 에러 처리, 히스토리 관리 |
