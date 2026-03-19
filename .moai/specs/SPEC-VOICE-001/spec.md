---
id: SPEC-VOICE-001
version: "1.0.0"
status: draft
created: "2026-03-19"
updated: "2026-03-19"
author: toby
priority: high
issue_number: 0
depends_on:
  - SPEC-PROVIDER-001
tags:
  - claude-api
  - supertonic-tts
  - korean-language
  - voice-assistant
---

# SPEC-VOICE-001: Claude LLM + Supertonic TTS + 한국어 통합

## 1. 환경 (Environment)

### 1.1 시스템 개요

본 SPEC은 AI 음성 비서의 핵심 Provider를 구현한다. 기존 Ollama LLM + Piper TTS(영어 전용) 조합을 Claude Sonnet API + Supertonic TTS(한국어 지원)로 전환하여, 한국어를 기본 언어로 동작하는 음성 비서를 완성한다.

### 1.2 기술 스택

| 구성요소 | 현재 | 변경 후 |
|---------|------|---------|
| LLM | Ollama (로컬, llama3) | Claude Sonnet API (클라우드) |
| TTS | Piper (ONNX, 영어) | Supertonic (ONNX, 한국어) |
| STT | faster-whisper (small.en) | faster-whisper (small, 다국어) |
| 언어 | English | Korean (한국어) |
| LLM Fallback | 없음 | OpenAI / Ollama |
| TTS Fallback | 없음 | OpenAI TTS |

### 1.3 의존성

- **SPEC-PROVIDER-001**: Provider 추상화 계층 (ABC: `LLMProvider`, `TTSProvider`, `STTProvider`)
  - `src/voice_assistant/providers/base.py` - 추상 베이스 클래스
  - `src/voice_assistant/providers/factory.py` - Provider 팩토리
  - `.env` 지원 - API 키 관리
  - `config.ini` Provider 선택 필드

### 1.4 외부 의존성

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `anthropic` | >= 0.40.0 | Claude API 클라이언트 |
| `supertonic` | latest stable | 온디바이스 TTS (ONNX) |
| `openai` | >= 1.50.0 | Fallback LLM/TTS |
| `python-dotenv` | >= 1.0.0 | .env 파일 로드 |

## 2. 가정 (Assumptions)

### 2.1 기술적 가정

- SPEC-PROVIDER-001이 완료되어 `LLMProvider`, `TTSProvider` ABC가 존재한다
- 사용자는 유효한 Anthropic API 키를 보유하고 있다
- Supertonic은 `pip install supertonic`으로 설치 가능하며, ONNX 모델을 자동 다운로드한다
- 기존 `sounddevice` 기반 오디오 출력 패턴을 Supertonic Provider에서도 재사용할 수 있다
- faster-whisper `small` 모델은 한국어 음성 인식을 지원한다

### 2.2 운영적 가정

- 인터넷 연결이 Claude API 호출에 필요하다
- 네트워크 불안정 시 Fallback Provider로 전환할 수 있다
- `.env` 파일에 API 키를 저장하며, 이 파일은 `.gitignore`에 포함된다

### 2.3 검증 필요 가정

- Supertonic의 한국어 음성 품질이 실사용에 충분한 수준인지 (신뢰도: 중간)
- Claude API 스트리밍 지연 시간이 음성 비서의 실시간 응답에 적합한지 (신뢰도: 높음)
- faster-whisper `small` 모델의 한국어 인식 정확도 (신뢰도: 중간)

## 3. 요구사항 (Requirements)

### 3.1 보편적 요구사항 (Ubiquitous)

- **[REQ-U-001]** 시스템은 **항상** Claude Sonnet API를 기본 LLM Provider로 사용해야 한다
- **[REQ-U-002]** 시스템은 **항상** Supertonic을 기본 TTS Provider로 사용하며 한국어 음성을 출력해야 한다
- **[REQ-U-003]** 시스템은 **항상** STT, TTS, 시스템 프롬프트에서 한국어를 기본 언어로 사용해야 한다
- **[REQ-U-004]** 시스템은 **항상** API 키를 `.env` 파일에서 로드하고, 코드에 하드코딩하지 않아야 한다

### 3.2 이벤트 기반 요구사항 (Event-Driven)

- **[REQ-E-001]** **WHEN** 사용자가 한국어로 말하면 **THEN** STT는 한국어 텍스트를 정확하게 변환해야 한다
- **[REQ-E-002]** **WHEN** LLM이 한국어 응답을 생성하면 **THEN** TTS는 한국어 음성을 합성해야 한다
- **[REQ-E-003]** **WHEN** Claude API 스트리밍이 토큰을 반환하면 **THEN** 시스템은 완성된 문장을 실시간으로 TTS 큐에 전달해야 한다
- **[REQ-E-004]** **WHEN** Claude API가 사용 불가능하면 **THEN** 시스템은 OpenAI 또는 로컬 Ollama로 폴백해야 한다
- **[REQ-E-005]** **WHEN** Supertonic 초기화 시 모델이 없으면 **THEN** 자동 다운로드(`auto_download=True`)로 모델을 획득해야 한다
- **[REQ-E-006]** **WHEN** 사용자가 config.ini에서 provider를 변경하면 **THEN** 시스템은 해당 provider를 로드해야 한다

### 3.3 상태 기반 요구사항 (State-Driven)

- **[REQ-S-001]** **IF** LLM이 스트리밍 응답 중이면 **THEN** 시스템은 완성된 문장 단위로 TTS에 전달해야 한다
- **[REQ-S-002]** **IF** TTS가 음성을 출력 중이면 **THEN** 새 문장은 큐에 추가되어 블로킹 없이 대기해야 한다
- **[REQ-S-003]** **IF** 네트워크가 불안정한 상태이면 **THEN** API 호출은 재시도 후 폴백 provider로 전환해야 한다

### 3.4 금지 요구사항 (Unwanted Behavior)

- **[REQ-N-001]** 시스템은 기본 동작에 Ollama 설치를 **요구하지 않아야 한다**
- **[REQ-N-002]** 시스템은 로그나 에러 메시지에 API 키를 **노출하지 않아야 한다**
- **[REQ-N-003]** 시스템은 기존 `VoiceAssistant` 클래스의 wake word 감지 및 대화 흐름을 **변경하지 않아야 한다**
- **[REQ-N-004]** 시스템은 API 키가 없는 경우 크래시를 **발생시키지 않아야 한다** (명확한 에러 메시지 출력)

### 3.5 선택적 요구사항 (Optional)

- **[REQ-O-001]** **가능하면** OpenAI TTS를 TTS 폴백 provider로 제공한다
- **[REQ-O-002]** **가능하면** OpenAI GPT를 LLM 폴백 provider로 제공한다
- **[REQ-O-003]** **가능하면** 대화 시작 시 한국어 확인 응답("네?")을 출력한다

## 4. 명세 (Specifications)

### 4.1 Claude LLM Provider (`claude_provider.py`)

- `LLMProvider` ABC를 구현한다
- `anthropic.Anthropic()` 클라이언트를 사용한다
- `client.messages.stream()` 으로 스트리밍 응답을 처리한다
- 모델: `claude-sonnet-4-20250514`
- 대화 히스토리 관리 (기존 `LLMHandler._prune_history` 패턴 유지)
- 한국어 시스템 프롬프트 기본 설정
- API 키는 환경변수 `ANTHROPIC_API_KEY`에서 로드
- 에러 발생 시 `None` yield 패턴으로 상위에 전달 (기존 패턴 유지)

### 4.2 Supertonic TTS Provider (`supertonic_provider.py`)

- `TTSProvider` ABC를 구현한다
- `TTS(auto_download=True)`로 초기화
- `tts.get_voice_style(voice_name="F3")`로 한국어 여성 음성 선택
- `tts.synthesize(text, voice)`로 음성 합성
- 기존 `Synthesizer` 클래스의 큐 기반 비동기 재생 패턴 유지
- `sounddevice.OutputStream`을 통한 오디오 출력 (기존 패턴)
- 리샘플링 로직 (필요 시 `scipy.signal.resample` 활용)

### 4.3 OpenAI LLM Provider (`openai_llm_provider.py`) [선택]

- `LLMProvider` ABC를 구현한다
- OpenAI Chat Completions API 스트리밍 사용
- API 키: 환경변수 `OPENAI_API_KEY`
- Claude API 폴백으로 동작

### 4.4 OpenAI TTS Provider (`openai_tts_provider.py`) [선택]

- `TTSProvider` ABC를 구현한다
- OpenAI TTS API 스트리밍 사용
- Supertonic 폴백으로 동작

### 4.5 설정 변경 사항

#### config.ini 기본값 변경

```ini
[Models]
llm_provider = claude
tts_provider = supertonic
whisper_model = small
language = ko

[Functionality]
system_prompt = 당신은 똑똑하고 재치 있는 한국어 음성 비서입니다. 모든 응답은 간결하게 한두 문장으로 해주세요. 정확하고, 재미있고, 간결하게.
```

#### faster-whisper 설정 변경

| 설정 | 변경 전 | 변경 후 | 이유 |
|------|---------|---------|------|
| `whisper_model` | `small.en` | `small` | 다국어 지원 필요 |
| `language` (transcribe) | `"en"` | `"ko"` | 한국어 인식 |
| `whisper_avg_logprob` | `-1.0` | `-1.2` | 한국어 인식 임계값 조정 |
| `whisper_no_speech_prob` | `0.65` | `0.7` | 한국어 특성 반영 |

### 4.6 `.env.example` 템플릿

```env
# AI Speaker Provider API Keys
ANTHROPIC_API_KEY=your-anthropic-api-key-here
OPENAI_API_KEY=your-openai-api-key-here

# Optional: Ollama (로컬 폴백)
OLLAMA_HOST=http://localhost:11434
```

## 5. 추적성 (Traceability)

| 요구사항 | 구현 파일 | 테스트 시나리오 |
|---------|----------|---------------|
| REQ-U-001 | `providers/claude_provider.py` | AC-001 |
| REQ-U-002 | `providers/supertonic_provider.py` | AC-002 |
| REQ-U-003 | `config.ini`, `transcriber.py` | AC-003 |
| REQ-E-001 | `transcriber.py` (설정 변경) | AC-003 |
| REQ-E-002 | `providers/supertonic_provider.py` | AC-002 |
| REQ-E-003 | `providers/claude_provider.py` | AC-001 |
| REQ-E-004 | `providers/factory.py` | AC-004 |
| REQ-S-001 | `voice_assistant.py` (기존 패턴) | AC-001 |
| REQ-S-002 | `providers/supertonic_provider.py` | AC-002 |
| REQ-N-001 | `config_manager.py` | AC-005 |
| REQ-N-002 | 전체 provider | AC-006 |
