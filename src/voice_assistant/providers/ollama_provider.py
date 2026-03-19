"""
providers/ollama_provider.py

Ollama LLM Provider 래퍼.
기존 LLMHandler 로직을 LLMProvider ABC로 래핑하여
팩토리 패턴을 통해 사용할 수 있도록 한다.
"""

import logging
from argparse import Namespace
from typing import Generator

import ollama

from .base import LLMProvider
from ..llm_handler import LLMHandler


class OllamaProvider(LLMProvider):
    """Ollama 기반 LLM Provider.

    기존 LLMHandler를 내부적으로 사용하여 Ollama 서버와 통신한다.
    config에서 ollama_host, ollama_model 설정을 읽어 클라이언트를 생성한다.
    """

    def __init__(self, config: Namespace) -> None:
        """Ollama Provider 초기화.

        Ollama 클라이언트를 생성하고 LLMHandler를 내부적으로 인스턴스화한다.

        Args:
            config: ollama_host, ollama_model, system_prompt 등을 포함하는 설정 객체

        Raises:
            ConnectionError: Ollama 서버에 연결할 수 없는 경우
        """
        super().__init__(config)

        ollama_host = getattr(config, "ollama_host", "http://localhost:11434")
        logging.info(f"Ollama 서버 연결 시도: {ollama_host}")

        try:
            self._client = ollama.Client(host=ollama_host)
            # 연결 테스트
            self._client.list()
            logging.info("Ollama 서버 연결 성공.")
        except Exception as e:
            logging.error(f"Ollama 서버 연결 실패 ({ollama_host}): {e}")
            raise ConnectionError(
                f"Ollama 서버에 연결할 수 없습니다 ({ollama_host}): {e}"
            ) from e

        # 기존 LLMHandler를 컴포지션으로 활용
        self._handler = LLMHandler(self._client, config)

    def chat_stream(self, user_text: str) -> Generator[str | None, None, None]:
        """사용자 입력에 대한 Ollama LLM 응답을 토큰 단위로 스트리밍.

        Args:
            user_text: 사용자 입력 텍스트

        Yields:
            str | None: 응답 토큰 문자열, 오류 시 None
        """
        yield from self._handler.chat_stream(user_text)

    def reset_history(self) -> None:
        """대화 히스토리 초기화."""
        self._handler.reset_history()

    def close(self) -> None:
        """리소스 정리. Ollama 클라이언트 참조 해제."""
        logging.debug("OllamaProvider 리소스 정리 중")
        self._client = None
        self._handler = None
