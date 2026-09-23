from fieldsight.aws.s3 import pdf_key
from fieldsight.aws.textract import start_analysis
from fieldsight.ingest.chunking import corpus_doc_ids
from fieldsight.errors import ExtractionError
from fieldsight.ingest.crack import wait_until_done

if __name__ == "__main__":
    # start every job first so Textract runs them side by side, then wait on each one
    jobs = {
        doc_id: start_analysis(pdf_key(doc_id, corpus=True), output_prefix=f"textract/{doc_id}")
        for doc_id in corpus_doc_ids()
    }

    failed = []
    for doc_id, job_id in jobs.items():
        status = wait_until_done(job_id)
        print(f"{doc_id}: {status}  ->  textract/{doc_id}/{job_id}/")

        # the corpus has to be complete, so a partial result counts as a failure here
        if status != "SUCCEEDED":
            failed.append(doc_id)

    if failed:
        print(f"Textract didn't fully succeed for: {', '.join(failed)}")