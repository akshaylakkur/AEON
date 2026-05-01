"""Cortex reasoning engine for AEON Hedge Fund Research Manager."""

from __future__ import annotations

from aeon.cortex.consequence_modeler import ConsequenceModeler
from aeon.cortex.dataclasses import (
    RecoveryAction,
    RecoveryStrategy,
    ReasoningReceipt,
)
from aeon.cortex.decision_engine import ResearchPriorityEngine
from aeon.cortex.executor import ResearchExecutor
from aeon.cortex.expansionism import (
    Allocation,
    ArbitrageExpansion,
    CapabilityRegistry,
    CapitalAllocator,
    ContentExpansion,
    ExpansionController,
    ExpansionStrategy,
    Goal,
    GoalPlanner,
    Milestone,
    NovelStrategyProposer,
    SaaSExpansion,
    StrategyPerformance,
    TradingExpansion,
    WealthTierManager,
)
from aeon.cortex.failure_recovery import FailureRecovery
from aeon.cortex.free_will import (
    UserPreferenceEngine,
    FreeWillEngine,
    GoalGenerator,
    SerendipityEngine,
)
from aeon.cortex.llm_client import ChatCost, LLMClient, LLMClientError
from aeon.cortex.llm_reasoning import LLMReasoner, LLMReasoningError, ReasoningResult
from aeon.cortex.meta_cognition import MetaCognition
from aeon.cortex.model_router import AbstractLLMProvider, ModelRouter, RoutingResult
from aeon.cortex.bedrock_provider import BedrockProvider
from aeon.cortex.ollama_provider import OllamaProvider
from aeon.cortex.planner import ResearchPlanner
from aeon.cortex.tool_registry import (
    LLMResponse,
    ToolCall,
    ToolDefinition,
    ToolExecutionError,
    ToolRegistry,
    ToolValidationError,
)

__all__ = [
    # LLM infrastructure
    "AbstractLLMProvider",
    "BedrockProvider",
    "ChatCost",
    "LLMClient",
    "LLMClientError",
    "LLMReasoner",
    "LLMReasoningError",
    "LLMResponse",
    "OllamaProvider",
    "ModelRouter",
    "ReasoningResult",
    "RoutingResult",
    # Tool registry
    "ToolCall",
    "ToolDefinition",
    "ToolExecutionError",
    "ToolRegistry",
    "ToolValidationError",
    # Research pipeline (new)
    "ResearchPriorityEngine",
    "ResearchExecutor",
    "ResearchPlanner",
    "ConsequenceModeler",
    "MetaCognition",
    "FailureRecovery",
    "UserPreferenceEngine",
    # Backwards-compatible aliases
    "FreeWillEngine",
    "GoalGenerator",
    "SerendipityEngine",
    # Dataclasses
    "RecoveryAction",
    "RecoveryStrategy",
    "ReasoningReceipt",
    # Expansion stubs (kept for import compatibility)
    "Allocation",
    "ArbitrageExpansion",
    "CapabilityRegistry",
    "CapitalAllocator",
    "ContentExpansion",
    "ExpansionController",
    "ExpansionStrategy",
    "Goal",
    "GoalPlanner",
    "Milestone",
    "NovelStrategyProposer",
    "SaaSExpansion",
    "StrategyPerformance",
    "TradingExpansion",
    "WealthTierManager",
]
