"""Redact this addon's secret-bearing call in Odoo's standard RPC debug log."""
import logging


class SecretCallFilter(logging.Filter):
    def filter(self, record):
        # Odoo 19 service.model.call_kw logs Params before the method executes.
        # Never stringify Params: it contains the submitted credential.
        args = record.args
        if record.msg == "call %s.%s(%s)" and isinstance(args, tuple) and len(args) == 3 and args[1] == "mdic_ai_save":
            record.args = (args[0], args[1], "[AI configuration arguments redacted]")
        return True


def install():
    logger = logging.getLogger("odoo.service.model")
    if not any(isinstance(item, SecretCallFilter) for item in logger.filters):
        logger.addFilter(SecretCallFilter())
