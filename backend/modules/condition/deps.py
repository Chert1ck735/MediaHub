from backend.modules.condition.services.condition_service import ConditionService


def get_condition_service() -> ConditionService:
    return ConditionService()
