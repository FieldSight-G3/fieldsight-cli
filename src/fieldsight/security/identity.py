""" who the analyst is: an STS caller proof, signed by the analyst's own assumed role, mapped to an enrolled analyst

    Identity never comes from a request field or a flag. The AgentCore Runtime verifies a proof the invoker sent;
    the CLI signs one with this machine's role credentials and verifies it the same way.
"""

from collections.abc import Callable
from uuid import UUID, uuid4

from ..errors import ToolDenied

AnalystResolver = Callable[[str, str], UUID]


def production_resolver() -> AnalystResolver:
    """ proof -> the exact enrolled analyst role -> that analyst's id; the session is the proof's bound thread """

    from ..config import settings
    from ..repository import AnalystRepository
    from .iam_caller_proof import enrolled_analyst_roles, verify_proof

    role_arns, account_id = enrolled_analyst_roles(settings.analyst_role_arns)
    analysts = AnalystRepository()

    def resolve(proof: str, session_id: str) -> UUID:
        role_arn = verify_proof(proof, session_id, settings.aws_region, account_id, role_arns)
        analyst_id = analysts.analyst_id_for_iam_principal(role_arn)
        if analyst_id is None:
            raise ToolDenied("not_entitled", "Caller has no enrolled analyst record")
        return analyst_id

    return resolve


def current_analyst() -> UUID:
    """ the analyst running this process: its assumed IAM role, proven to STS and mapped to an enrolled analyst """

    from ..config import settings
    from .iam_caller_proof import issue_proof

    session = f"cli-{uuid4()}"
    return production_resolver()(issue_proof(session, settings.aws_region), session)
