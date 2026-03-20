# AI Speaker 프로젝트 대화 요약

날짜: 2026-03-19 ~ 2026-03-20
참여자: toby, MoAI (Claude Code)

## 프로젝트 목표

Mac Mini + 무지향성 마이크 스피커폰으로 가족용 AI 음성 비서 구축.
ollama-STT-TTS 포크를 기반으로 다양한 클라우드 API를 연결하여 실용적인 AI 스피커로 만드는 것.
잘 만들면 부모님께 설치해드릴 계획.

## 기술 스택 결정

- LLM: Claude Sonnet API (기본), OpenAI 폴백
- TTS: Supertonic(로컬) -> Supertone Play(클라우드) -> OpenAI TTS로 변경 중
  - Supertonic: 로컬 ONNX, 무료, 한국어 지원이지만 부자연스러운 음성
  - Supertone Play: 고품질이지만 비용 과다 ($5.99/50분, 테스트 몇 번에 600크레딧 소모)
  - OpenAI TTS: $15/1M글자, 가성비 좋음. API 키 환경변수 문제 수정 후 테스트 중
  - Grok TTS: $4.20/1M글자로 가장 저렴. 아직 미구현
- STT: faster-whisper (로컬, small 다국어 모델, 한국어)
- 웨이크워드: OpenWakeWord "hey jarvis" (한국어 "챱츄야"로 변경 희망)
- 기본 언어: 한국어

## 구현 완료 사항

### SPEC-PROVIDER-001: Provider 추상화 계층
- LLM/TTS/STT Provider ABC (base.py)
- ProviderFactory (factory.py) - 레지스트리 + 폴백
- 레거시 래퍼: OllamaProvider, PiperProvider, WhisperProvider
- python-dotenv 통합 (.env 기반 API 키 관리)
- config.ini [Providers] 섹션 추가
- 조건부 Provider 등록 (의존성 없으면 건너뜀)

### SPEC-VOICE-001: Claude + Supertonic + 한국어 통합
- ClaudeProvider: Claude Sonnet API 스트리밍, 한국어 시스템 프롬프트
- SupertonicProvider: 로컬 ONNX TTS (한국어 음성 F3)
- SupertonePlayProvider: Supertone Play API (클라우드 TTS)
- OpenAITTSProvider: OpenAI TTS API
- faster-whisper 한국어 설정 (small 모델, language="ko")
- config.ini 한국어 기본값 설정

## 버그 수정

1. 웨이크워드 재인식 실패: 대화 후 oww_model.reset() 추가
2. 웨이크워드 평균 점수 조건 과도: avg_score 조건 제거, consecutive만 체크
3. 웨이크워드 민감도: threshold 0.40->0.30, consecutive 2->1
4. 문장 끊김: 마침표 위치에서 정확히 분리하도록 수정
5. .env 환경변수 우선순위: load_dotenv(override=True)로 수정
6. pkg_resources 미설치: setuptools 75.8.2로 다운그레이드
7. OpenWakeWord 모델 누락: download_models() 실행
8. 오디오 출력 장치: piper_output_device_index를 3(iMac 스피커)으로 변경

## 미해결/진행 중

- OpenAI TTS 테스트 (API 키 문제 해결됨, 테스트 필요)
- Grok TTS Provider 구현 예정 ($4.20/1M글자)
- "챱츄야" 웨이크워드 구현 (STT 기반 감지 방식)
- 프롬프트 로그 훅 추가됨 (.moai/logs/prompt-log.jsonl)

## 커밋 히스토리

```
09d551f chore: MoAI-ADK 프레임워크 설정 추가
59d0e3e feat: Provider 추상화 계층 및 Claude/Supertonic 통합
0cd5b1d fix: 오디오 출력 장치 인덱스를 iMac 스피커로 변경
```

## 비용 참고

| 서비스 | 가격 | 비고 |
|--------|------|------|
| Supertone Play | $5.99/50분 | 테스트 몇 번에 600크레딧 (비쌈) |
| OpenAI TTS | $15/1M글자 | 월 1000회 대화 ~$1.5 |
| Grok TTS | $4.20/1M글자 | 가장 저렴 |
| Claude Sonnet | $3/$15 (입/출력 1M토큰) | LLM 비용 |
