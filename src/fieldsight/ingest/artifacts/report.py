""" the ingestion report for a packet """

from ...types.artifacts import INGESTION_REPORT, IngestionReport, PacketExtraction


def ingestion_report(extraction: PacketExtraction, floor: float) -> IngestionReport:
    """ artifacts processed, fields extracted, the labels of fields below the confidence floor, and failures """

    return INGESTION_REPORT.validate_python({
        "artifacts_processed": len(extraction["artifacts"]),
        "fields_extracted": len(extraction["fields"]),
        "fields_below_floor": [field["label"] for field in extraction["fields"] if field["confidence"] < floor],
        "failures": extraction["failures"],
    })
