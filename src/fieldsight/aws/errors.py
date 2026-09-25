""" turn boto failures into FieldSight's own errors, as a decorator on the AWS calls """

from functools import wraps

from botocore.exceptions import BotoCoreError, ClientError

from ..errors import FieldSightError


def raises(error: type[FieldSightError], action: str):
    """ any boto failure inside the wrapped call is re-raised as `error`, naming what was being done """

    def decorate(call):
        @wraps(call)
        def wrapped(*args, **kwargs):
            try:
                return call(*args, **kwargs)
            except (BotoCoreError, ClientError) as cause:
                raise error(f"{action}: {cause}") from cause
        return wrapped
    return decorate
