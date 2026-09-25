""" FieldSight's own exceptions, so extraction, retrieval, rules, and gate failures can be told apart by type """


class FieldSightError(Exception):
    """ base class for every error FieldSight raises on purpose """


class ExtractionError(FieldSightError):
    """ Textract couldn't crack an artifact or corpus doc """


class IndexingError(FieldSightError):
    """ the corpus couldn't be written to, or synced into, the Knowledge Base """


class RetrievalError(FieldSightError):
    """ the corpus Knowledge Base couldn't be searched, so nothing can be grounded """
