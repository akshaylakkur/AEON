"""Public API for aeon.metamind — the self-modification and adaptation system."""

from aeon.metamind.adaption_engine import AdaptionConfig, AdaptionEngine
from aeon.metamind.ci_cd_generator import CICDArtifact, CICDGenerator
from aeon.metamind.code_generator import CodeGenerator, LLMProvider
from aeon.metamind.code_introspector import (
    ClassLocation,
    CodeIntrospector,
    FunctionLocation,
    IntrospectionError,
    ModuleComplexity,
    ParseError,
    SelfModificationError,
)
from aeon.metamind.dataclasses import (
    AdaptationProposal,
    ClassInfo,
    DecisionType,
    EvolutionResult,
    FunctionInfo,
    GeneratedCode,
    JournalEntry,
    ModuleInfo,
    SafetyRating,
    SourceMap,
    SystemMetrics,
)
from aeon.metamind.dependency_manager import (
    DependencyError,
    DependencyManager,
    DependencyReport,
    InstallError,
    UnresolvableImportError,
)
from aeon.metamind.deployment_manager import DeploymentError, DeploymentManager, DeploymentRecord
from aeon.metamind.evolution_gate import EvolutionGate
from aeon.metamind.marketplace_lister import ListingRecord, MarketplaceError, MarketplaceLister
from aeon.metamind.module_generator import (
    GeneratedCode as ModuleGeneratedCode,
    GenerationError,
    ModuleGenerator,
    ModuleSpecification,
    TemplateNotFoundError,
)
from aeon.metamind.patch_applier import (
    CodePatch,
    DiffParseError,
    HunkApplyError,
    PatchApplier,
    PatchError,
    PatchResult,
    RollbackError,
    RollbackResult,
    TestRunner,
)
from aeon.metamind.product_manager import (
    CostEstimate,
    MarketOpportunity,
    ProductCategory,
    ProductManager,
    ProductRecord,
    ProductStage,
)
from aeon.metamind.rollback_journal import PatchRecord, RollbackJournal
from aeon.metamind.revenue_tracker import ProductMetrics, RevenueEvent, RevenueTracker
from aeon.metamind.schema_evolver import (
    ConfigCorruptionError,
    MigrationProposal,
    MigrationRecord,
    MigrationResult,
    SchemaEvolver,
    SchemaMigrationError,
)
from aeon.metamind.self_analyzer import SelfAnalyzer
from aeon.metamind.self_modification_engine import (
    ModificationResult,
    SelfModificationEngine,
    TierGateError,
)
from aeon.metamind.strategy_journal import StrategyJournal

__all__ = [
    "AdaptionConfig",
    "AdaptionEngine",
    "AdaptationProposal",
    "CICDArtifact",
    "CICDGenerator",
    "ClassInfo",
    "ClassLocation",
    "CodeGenerator",
    "CodeIntrospector",
    "CodePatch",
    "ConfigCorruptionError",
    "CostEstimate",
    "DecisionType",
    "DeploymentError",
    "DeploymentManager",
    "DeploymentRecord",
    "DependencyError",
    "DependencyManager",
    "DependencyReport",
    "DiffParseError",
    "EvolutionGate",
    "EvolutionResult",
    "FunctionInfo",
    "FunctionLocation",
    "GeneratedCode",
    "GenerationError",
    "HunkApplyError",
    "InstallError",
    "IntrospectionError",
    "JournalEntry",
    "LLMProvider",
    "ListingRecord",
    "MarketOpportunity",
    "MarketplaceError",
    "MarketplaceLister",
    "MigrationProposal",
    "MigrationRecord",
    "MigrationResult",
    "ModuleComplexity",
    "ModuleGeneratedCode",
    "ModuleGenerator",
    "ModuleInfo",
    "ModuleSpecification",
    "ModificationResult",
    "ParseError",
    "PatchApplier",
    "PatchError",
    "PatchRecord",
    "PatchResult",
    "ProductCategory",
    "ProductManager",
    "ProductMetrics",
    "ProductRecord",
    "ProductStage",
    "RevenueEvent",
    "RevenueTracker",
    "RollbackError",
    "RollbackJournal",
    "RollbackResult",
    "SafetyRating",
    "SchemaEvolver",
    "SchemaMigrationError",
    "SelfAnalyzer",
    "SelfModificationEngine",
    "SelfModificationError",
    "SourceMap",
    "StrategyJournal",
    "SystemMetrics",
    "TemplateNotFoundError",
    "TestRunner",
    "TierGateError",
    "UnresolvableImportError",
]
