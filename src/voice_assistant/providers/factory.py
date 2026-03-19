"""
providers/factory.py

Provider 팩토리 클래스.
config.ini 설정에 따라 적절한 Provider 인스턴스를 생성하고,
클라우드 Provider 실패 시 로컬 Provider로 폴백하는 로직을 포함한다.
"""

import logging
import threading
from argparse import Namespace
from typing import Dict, Type

from .base import LLMProvider, STTProvider, TTSProvider

# 카테고리별 기본 로컬 Provider 이름
_DEFAULT_LLM: str = "ollama"
_DEFAULT_TTS: str = "piper"
_DEFAULT_STT: str = "whisper"


class ProviderFactory:
    """Provider 팩토리 클래스.

    내부 레지스트리에 등록된 Provider를 이름 기반으로 생성한다.
    Provider 초기화 실패 시 기본 로컬 Provider로 자동 폴백한다.
    """

    # Provider 레지스트리 (카테고리별)
    _LLM_REGISTRY: Dict[str, Type[LLMProvider]] = {}
    _TTS_REGISTRY: Dict[str, Type[TTSProvider]] = {}
    _STT_REGISTRY: Dict[str, Type[STTProvider]] = {}

    @classmethod
    def register_llm(cls, name: str, provider_cls: Type[LLMProvider]) -> None:
        """LLM Provider를 레지스트리에 등록.

        Args:
            name: Provider 이름 (소문자)
            provider_cls: LLMProvider를 상속한 클래스
        """
        cls._LLM_REGISTRY[name.strip().lower()] = provider_cls

    @classmethod
    def register_tts(cls, name: str, provider_cls: Type[TTSProvider]) -> None:
        """TTS Provider를 레지스트리에 등록.

        Args:
            name: Provider 이름 (소문자)
            provider_cls: TTSProvider를 상속한 클래스
        """
        cls._TTS_REGISTRY[name.strip().lower()] = provider_cls

    @classmethod
    def register_stt(cls, name: str, provider_cls: Type[STTProvider]) -> None:
        """STT Provider를 레지스트리에 등록.

        Args:
            name: Provider 이름 (소문자)
            provider_cls: STTProvider를 상속한 클래스
        """
        cls._STT_REGISTRY[name.strip().lower()] = provider_cls

    @classmethod
    def create_llm(cls, provider_name: str, config: Namespace) -> LLMProvider:
        """LLM Provider 인스턴스를 생성.

        Args:
            provider_name: Provider 이름 (예: "ollama", "claude")
            config: argparse.Namespace 설정 객체

        Returns:
            LLMProvider 인스턴스

        Raises:
            ValueError: 알 수 없는 Provider 이름이고 폴백도 실패한 경우
        """
        name = provider_name.strip().lower()
        return cls._create_provider(
            name=name,
            registry=cls._LLM_REGISTRY,
            category="LLM",
            default_name=_DEFAULT_LLM,
            config=config,
        )

    @classmethod
    def create_tts(
        cls,
        provider_name: str,
        config: Namespace,
        interrupt_event: threading.Event,
    ) -> TTSProvider:
        """TTS Provider 인스턴스를 생성.

        Args:
            provider_name: Provider 이름 (예: "piper", "openai")
            config: argparse.Namespace 설정 객체
            interrupt_event: 외부 인터럽트 이벤트

        Returns:
            TTSProvider 인스턴스

        Raises:
            ValueError: 알 수 없는 Provider 이름이고 폴백도 실패한 경우
        """
        name = provider_name.strip().lower()
        return cls._create_provider(
            name=name,
            registry=cls._TTS_REGISTRY,
            category="TTS",
            default_name=_DEFAULT_TTS,
            config=config,
            interrupt_event=interrupt_event,
        )

    @classmethod
    def create_stt(cls, provider_name: str, config: Namespace) -> STTProvider:
        """STT Provider 인스턴스를 생성.

        Args:
            provider_name: Provider 이름 (예: "whisper", "openai")
            config: argparse.Namespace 설정 객체

        Returns:
            STTProvider 인스턴스

        Raises:
            ValueError: 알 수 없는 Provider 이름이고 폴백도 실패한 경우
        """
        name = provider_name.strip().lower()
        return cls._create_provider(
            name=name,
            registry=cls._STT_REGISTRY,
            category="STT",
            default_name=_DEFAULT_STT,
            config=config,
        )

    @classmethod
    def _create_provider(
        cls,
        name: str,
        registry: dict,
        category: str,
        default_name: str,
        config: Namespace,
        interrupt_event: threading.Event | None = None,
    ):
        """Provider 생성 공통 로직. 실패 시 기본 Provider로 폴백.

        Args:
            name: 정규화된 Provider 이름
            registry: 해당 카테고리의 Provider 레지스트리
            category: 카테고리 이름 (로깅용: "LLM", "TTS", "STT")
            default_name: 폴백할 기본 Provider 이름
            config: 설정 객체
            interrupt_event: TTS Provider용 인터럽트 이벤트 (TTS에만 해당)

        Returns:
            생성된 Provider 인스턴스

        Raises:
            ValueError: 레지스트리에 Provider가 없고 폴백도 불가능한 경우
        """
        available = list(registry.keys())

        # 레지스트리에 없는 Provider 이름인 경우
        if name not in registry:
            raise ValueError(
                f"알 수 없는 {category} Provider: '{name}'. "
                f"사용 가능한 Provider: {available}"
            )

        # 요청된 Provider 초기화 시도
        try:
            return cls._instantiate(registry[name], config, interrupt_event)
        except Exception as e:
            logging.error(
                f"{category} Provider '{name}' 초기화 실패: {e}"
            )

            # 이미 기본 Provider를 요청한 경우 폴백 불가 -> 예외 전파
            if name == default_name:
                raise

            # 기본 로컬 Provider로 폴백 시도
            if default_name in registry:
                logging.warning(
                    f"기본 {category} Provider '{default_name}'(으)로 폴백합니다."
                )
                try:
                    return cls._instantiate(
                        registry[default_name], config, interrupt_event
                    )
                except Exception as fallback_err:
                    logging.error(
                        f"폴백 {category} Provider '{default_name}' 초기화도 실패: "
                        f"{fallback_err}"
                    )
                    raise
            else:
                raise

    @staticmethod
    def _instantiate(
        provider_cls: type,
        config: Namespace,
        interrupt_event: threading.Event | None,
    ):
        """Provider 클래스를 인스턴스화.

        TTS Provider는 interrupt_event를 추가 인자로 받는다.

        Args:
            provider_cls: Provider 클래스
            config: 설정 객체
            interrupt_event: TTS용 인터럽트 이벤트

        Returns:
            Provider 인스턴스
        """
        if interrupt_event is not None and issubclass(provider_cls, TTSProvider):
            return provider_cls(config, interrupt_event)
        return provider_cls(config)
