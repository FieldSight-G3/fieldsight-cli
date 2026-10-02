"""A sentence restating a rule decision is grounded by a provision that rule applied, never by whatever was nearby."""

from fieldsight.rules.proposal_review import rule_citation_problems
from fieldsight.schemas.rule_proposal import ClassificationProposal

DECISIONS = {
    "R3": {"rule_id": "R3", "outcome": "beyond_first_aid", "sources": ["29 CFR 1904.7(b)(5)(ii)"]},
    "R4": {"rule_id": "R4", "outcome": "J", "sources": ["29 CFR 1904.7(b)(5)", "29 CFR 1904.29(b)(3)"]},
}
RETRIEVED = {
    "reg-1904.7": {"doc_id": "CFR-1904", "section_path": "1904.7", "paragraph": "1904.7(b)(5)(ii)",
                   "text": "(ii) What is first aid? ... (D) ... sutures, staples, etc., are considered medical treatment"},
    "list-opening": {"doc_id": "CFR-1904", "section_path": "1904.7", "paragraph": "1904.7(b)(5)",
                     "text": "(5) How do I record an injury or illness that involves medical treatment beyond first aid?"},
    "cpl-ix-e": {"doc_id": "CPL-172", "section_path": "IX.E", "paragraph": "IX.E"},
    "form-301": {"doc_id": "FORM-301", "section_path": "overview", "paragraph": "overview"},
}


def proposal(rationale: str, chunk_ids: list[str]) -> ClassificationProposal:
    return ClassificationProposal.model_validate({"outcome": "recordable", "log_column": "J", "day_count": None,
                                                  "rationale": rationale, "chunk_ids": chunk_ids})


def test_a_rule_sentence_citing_the_rules_own_section_passes():
    assert rule_citation_problems(proposal("R3 found sutures beyond first aid [1].", ["reg-1904.7"]), DECISIONS, RETRIEVED) == []


def test_a_rule_sentence_citing_only_commentary_is_sent_back_with_the_provision_named():
    [problem] = rule_citation_problems(proposal("R3 found sutures beyond first aid [1].", ["cpl-ix-e"]), DECISIONS, RETRIEVED)
    assert "R3" in problem and "read_provision" in problem and "29 CFR 1904.7(b)(5)(ii)" in problem


def test_a_chunk_from_the_right_section_but_the_wrong_paragraph_is_sent_back():
    # the section-level check let this through; the paragraph doesn't state the first-aid list
    assert rule_citation_problems(proposal("R3 found sutures beyond first aid [1].", ["list-opening"]), DECISIONS, RETRIEVED)


def test_the_column_rests_on_its_1904_7_paragraph_not_a_form():
    # the corpus has no Form 300 column definitions, so R4 no longer lists them and a form chunk grounds nothing
    assert rule_citation_problems(proposal("R4 placed it in column J [1].", ["list-opening"]), DECISIONS, RETRIEVED) == []
    assert rule_citation_problems(proposal("R4 placed it in column J [1].", ["form-301"]), DECISIONS, RETRIEVED)


def test_a_sentence_naming_no_rule_is_left_to_the_reviewer():
    assert rule_citation_problems(proposal("Sutures close a wound [1].", ["cpl-ix-e"]), DECISIONS, RETRIEVED) == []


def test_r4_cites_the_paragraph_for_the_column_it_chose():
    from fieldsight.rules.log_classification import log_classification
    from fieldsight.schemas.rule_input import R4Inputs

    def column(**facts):
        decision = log_classification(R4Inputs.model_validate({"recordable": True, "death": False, "days_away": 0,
                                                               "restricted_days": 0, "job_transfer": False} | facts))
        return decision.outcome, decision.sources[0]

    assert column() == ("J", "29 CFR 1904.7(b)(5)")
    assert column(days_away=3) == ("H", "29 CFR 1904.7(b)(3)")
    assert column(restricted_days=2) == ("I", "29 CFR 1904.7(b)(4)")
    assert column(death=True) == ("G", "29 CFR 1904.7(b)(2)")
