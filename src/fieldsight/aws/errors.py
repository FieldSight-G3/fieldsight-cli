""" decorator that re-raises boto failures as FieldSight errors """

from functools import wraps

from botocore.exceptions import BotoCoreError, ClientError

from ..errors import FieldSightError


def raises(error: type[FieldSightError], action: str):
    """ re-raise boto failures in the wrapped call as `error`, prefixed with `action` """

    def decorate(call):
        @wraps(call)
        def wrapped(*args, **kwargs):
            try:
                return call(*args, **kwargs)
            except (BotoCoreError, ClientError) as cause:
                raise error(f"{action}: {cause}") from cause
        return wrapped
    return decorate
