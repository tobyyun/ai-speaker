"""
providers/claude_provider.py

Claude LLM Provider.
Anthropic Claude Sonnet API를 사용하여 스트리밍 방식으로 LLM 응답을 제공한다.
시스템 프롬프트는 messages 리스트가 아닌 별도의 system 파라미터로 전달한다.
"""

import gc
import logging
import os
from argparse import Namespace
from typing import Generator

from .base import LLMProvider


def _mask_api_key(key: str) -> str:
    """API 키를 로그에 안전하게 표시하기 위해 마스킹.

    Args:
        key: 원본 API 키 문자열

    Returns:
        앞 4자리만 보이고 나머지는 '...'으로 대체된 문자열
    """
    if not key or len(key) < 8:
        return "****"
    return key[:4] + "..."


class ClaudeProvider(LLMProvider):
    """Anthropic Claude 기반 LLM Provider.

    Claude Sonnet API를 사용하여 한국어 음성 비서에 최적화된 응답을 생성한다.
    스트리밍 방식으로 토큰을 전달하여 실시간 TTS 파이프라인과 호환된다.

    주요 특징:
        - client.messages.stream()을 통한 실시간 토큰 스트리밍
        - system 파라미터를 통한 시스템 프롬프트 전달 (messages와 분리)
        - 대화 히스토리 관리 및 자동 정리
        - API 키 마스킹으로 로그 보안 유지
    """

    def __init__(self, config: Namespace) -> None:
        """Claude Provider 초기화.

        환경변수에서 API 키를 로드하고 Anthropic 클라이언트를 생성한다.

        Args:
            config: model, max_tokens, system_prompt 등을 포함하는 설정 객체

        Raises:
            ValueError: ANTHROPIC_API_KEY 환경변수가 설정되지 않은 경우
        """
        super().__init__(config)

        # 환경변수에서 API 키 로드
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다. "
                ".env 파일에 API 키를 설정하거나 환경변수를 직접 설정해주세요."
            )

        logging.info(
            f"Claude Provider 초기화 중... (API 키: {_mask_api_key(api_key)})"
        )

        # anthropic 패키지 임포트 (optional dependency)
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)

        # 모델 및 토큰 설정
        self._model: str = getattr(config, "claude_model", "claude-sonnet-4-20250514")
        self._max_tokens: int = getattr(config, "claude_max_tokens", 512)

        # 대화 히스토리 (user/assistant 역할만 포함, system은 별도 파라미터)
        self.messages: list[dict[str, str]] = []

        # 히스토리 최대 쌍 수 (기존 LLMHandler 패턴 유지)
        self._max_pairs: int = getattr(config, "max_history_tokens", 2048) // 100

        # 비서 이름을 시스템 프롬프트에 반영
        from ..tools import load_state
        state = load_state()
        assistant_name = state.get("name", "챱츄")
        self.system_prompt = (
            f"당신의 이름은 '{assistant_name}'입니다. "
            f"절대로 먼저 이름을 말하지 마세요. 사용자가 '이름이 뭐야?'라고 직접 물어볼 때만 이름을 답하세요. "
            f"답변 시작할 때 자기소개, 인사, 이름 언급을 하지 마세요. 바로 본론만 말하세요. " +
            self.system_prompt
        )

        logging.info(
            f"Claude Provider 초기화 완료. 모델: {self._model}, "
            f"최대 토큰: {self._max_tokens}, 비서 이름: {assistant_name}"
        )

    def chat_stream(self, user_text: str) -> Generator[str | None, None, None]:
        """사용자 입력에 대한 Claude 응답을 토큰 단위로 스트리밍.

        Tool Use를 지원하여 시간 조회, 웹 검색 등을 Claude가 자동으로 판단하여 호출한다.
        도구 호출이 필요한 경우 도구를 실행하고 결과를 포함하여 최종 응답을 생성한다.

        Args:
            user_text: 사용자 입력 텍스트

        Yields:
            str | None: 응답 토큰 문자열, 오류 시 None
        """
        import anthropic
        from ..tools import TOOLS, execute_tool

        # 사용자 메시지를 히스토리에 추가
        self.messages.append({"role": "user", "content": user_text})
        self._prune_history()

        try:
            # 1단계: 도구 사용 여부 판단 (non-streaming)
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self.system_prompt,
                messages=self.messages,
                tools=TOOLS,
            )

            # 도구 호출이 없으면 바로 텍스트 반환
            if response.stop_reason != "tool_use":
                full_response = ""
                for block in response.content:
                    if block.type == "text":
                        full_response += block.text
                        yield block.text
                self.messages.append({"role": "assistant", "content": full_response})
                return

            # 2단계: 도구 실행
            # assistant 응답(tool_use 포함)을 히스토리에 추가
            self.messages.append({"role": "assistant", "content": response.content})

            # 각 도구 호출 실행
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    logging.info(f"도구 호출: {block.name}({block.input})")
                    result = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            # 도구 결과를 히스토리에 추가
            self.messages.append({"role": "user", "content": tool_results})

            # 3단계: 도구 결과를 포함하여 최종 응답 생성
            full_response = ""
            with self._client.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self.system_prompt,
                messages=self.messages,
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield text

            self.messages.append({"role": "assistant", "content": full_response})

        except anthropic.AuthenticationError:
            logging.error("Claude API 인증 실패. ANTHROPIC_API_KEY를 확인해주세요.")
            if self.messages and self.messages[-1]["role"] == "user":
                self.messages.pop()
            yield None

        except anthropic.RateLimitError:
            logging.warning("Claude API 속도 제한 초과. 잠시 후 다시 시도해주세요.")
            if self.messages and self.messages[-1]["role"] == "user":
                self.messages.pop()
            yield None

        except anthropic.APIConnectionError as e:
            logging.error(f"Claude API 연결 오류: {e}")
            if self.messages and self.messages[-1]["role"] == "user":
                self.messages.pop()
            yield None

        except Exception as e:
            logging.error(f"Claude API 예기치 않은 오류: {e}")
            if self.messages and self.messages[-1]["role"] == "user":
                self.messages.pop()
            yield None

    def reset_history(self) -> None:
        """대화 히스토리 초기화.

        Claude API는 system 프롬프트를 별도 파라미터로 전달하므로
        messages 리스트에는 user/assistant 역할만 포함된다.
        """
        self.messages = []

    def close(self) -> None:
        """리소스 정리 및 클라이언트 참조 해제."""
        logging.debug("ClaudeProvider 리소스 정리 중")
        self._client = None
        self.messages = []

    def _prune_history(self) -> None:
        """대화 히스토리를 최근 N쌍만 유지하도록 정리.

        기존 LLMHandler._prune_history() 패턴을 유지한다.
        Claude는 system 프롬프트가 messages에 포함되지 않으므로
        user/assistant 쌍만 관리하면 된다.
        """
        max_messages = self._max_pairs * 2

        if len(self.messages) > max_messages:
            # 최근 메시지만 유지
            self.messages = self.messages[-max_messages:]

            # 히스토리 정리 후 가비지 컬렉션
            gc.collect()
