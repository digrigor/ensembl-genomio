from .base import BaseRule

class IgnoreRule(BaseRule):
  NAME = "IGNORE"
  _RULES = BaseRule.RulesType()