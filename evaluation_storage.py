import json
from pathlib import Path
from datetime import datetime

EVALUATIONS_FILE = Path(__file__).parent / "evaluations.json"


def load_evaluations() -> dict:
    """Load all evaluations from local JSON file."""
    if EVALUATIONS_FILE.exists():
        try:
            with open(EVALUATIONS_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_evaluations(evaluations: dict):
    """Save all evaluations to local JSON file."""
    with open(EVALUATIONS_FILE, 'w') as f:
        json.dump(evaluations, f, indent=2, default=str)


def make_key(evaluator: str, document_id: str) -> str:
    """Create a unique key for an evaluator+note pair."""
    return f"{evaluator}_{document_id}"


def _empty_model_eval() -> dict:
    return {
        "hallucination_fabrication": None,
        "hallucination_fabrication_findings": "",
        "hallucination_inference": None,
        "inference_breakdown": None,
        "hallucination_inference_findings": "",
        "pertinent_omission": None,
        "omission_findings": "",
        "omission_severity": None,
        "extraneous_info": None,
        "extraneous_findings": "",
        "extraneous_severity": None,
        "flow": None,
        "flow_findings": "",
    }


def _empty_evaluation(evaluator: str, document_id: str, group: str) -> dict:
    return {
        "document_id": document_id,
        "evaluator": evaluator,
        "group": group,
        "status": "not_started",
        "timestamp": None,
        "model_1_eval": _empty_model_eval(),
        "model_2_eval": _empty_model_eval(),
        "model_3_eval": _empty_model_eval(),
        "preference": None,
        "preference_reasons": "",
        "comment_one_liner": "",
        "comment_visit_summary": "",
    }


def get_evaluation(evaluator: str, document_id: str, group: str = "") -> dict:
    """Get evaluation for a specific evaluator+note pair. Creates empty if missing."""
    evaluations = load_evaluations()
    key = make_key(evaluator, document_id)
    if key not in evaluations:
        return _empty_evaluation(evaluator, document_id, group)
    return evaluations[key]


def save_progress(evaluator: str, document_id: str, group: str, data: dict):
    """Save partial evaluation (no validation). Marks status as in_progress."""
    evaluations = load_evaluations()
    key = make_key(evaluator, document_id)

    if key not in evaluations:
        evaluations[key] = _empty_evaluation(evaluator, document_id, group)

    # Merge in provided data
    for k, v in data.items():
        if k in ("model_1_eval", "model_2_eval", "model_3_eval"):
            evaluations[key][k].update(v)
        else:
            evaluations[key][k] = v

    evaluations[key]["status"] = "in_progress"
    evaluations[key]["timestamp"] = datetime.now().isoformat()
    save_evaluations(evaluations)


def submit_evaluation(evaluator: str, document_id: str, group: str, data: dict):
    """Submit a completed evaluation. Marks status as completed."""
    evaluations = load_evaluations()
    key = make_key(evaluator, document_id)

    if key not in evaluations:
        evaluations[key] = _empty_evaluation(evaluator, document_id, group)

    for k, v in data.items():
        if k in ("model_1_eval", "model_2_eval", "model_3_eval"):
            evaluations[key][k].update(v)
        else:
            evaluations[key][k] = v

    evaluations[key]["status"] = "completed"
    evaluations[key]["timestamp"] = datetime.now().isoformat()
    save_evaluations(evaluations)


def get_evaluator_progress(evaluator: str, document_ids: list) -> dict:
    """Get progress summary for an evaluator across their assigned notes."""
    evaluations = load_evaluations()
    progress = {"completed": 0, "in_progress": 0, "not_started": 0, "total": len(document_ids)}

    for doc_id in document_ids:
        key = make_key(evaluator, doc_id)
        if key in evaluations:
            status = evaluations[key].get("status", "not_started")
            if status == "completed":
                progress["completed"] += 1
            elif status == "in_progress":
                progress["in_progress"] += 1
            else:
                progress["not_started"] += 1
        else:
            progress["not_started"] += 1

    return progress


def get_note_status(evaluator: str, document_id: str) -> str:
    """Get the status of a specific note for an evaluator."""
    evaluations = load_evaluations()
    key = make_key(evaluator, document_id)
    if key in evaluations:
        return evaluations[key].get("status", "not_started")
    return "not_started"


def get_all_progress() -> dict:
    """Get progress for all evaluators (for admin dashboard)."""
    evaluations = load_evaluations()
    progress = {}

    for key, eval_data in evaluations.items():
        evaluator = eval_data.get("evaluator", "Unknown")
        if evaluator not in progress:
            progress[evaluator] = {"completed": 0, "in_progress": 0, "total": 0}
        progress[evaluator]["total"] += 1
        status = eval_data.get("status", "not_started")
        if status == "completed":
            progress[evaluator]["completed"] += 1
        elif status == "in_progress":
            progress[evaluator]["in_progress"] += 1

    return progress


def rebuild_from_submissions(submissions: list) -> int:
    """Rebuild local evaluations from Google Sheets submissions. Returns count recovered."""
    evaluations = load_evaluations()
    count = 0

    for sub in submissions:
        evaluator = sub.get("evaluator", "")
        doc_id = sub.get("documentId", "")
        if not evaluator or not doc_id:
            continue

        key = make_key(evaluator, doc_id)

        # Build model eval dicts from flat payload
        model_evals = {}
        for m_num, prefix in [("1", "m1_"), ("2", "m2_"), ("3", "m3_")]:
            model_evals[f"model_{m_num}_eval"] = {
                "hallucination_fabrication": sub.get(f"{prefix}hall_fab", ""),
                "hallucination_fabrication_findings": sub.get(f"{prefix}hall_fab_f", ""),
                "hallucination_inference": sub.get(f"{prefix}hall_inf", ""),
                "inference_breakdown": sub.get(f"{prefix}inf_breakdown", ""),
                "hallucination_inference_findings": sub.get(f"{prefix}hall_inf_f", ""),
                "pertinent_omission": sub.get(f"{prefix}omission", ""),
                "omission_findings": sub.get(f"{prefix}omission_f", ""),
                "omission_severity": sub.get(f"{prefix}omission_sev", ""),
                "extraneous_info": sub.get(f"{prefix}extraneous", ""),
                "extraneous_findings": sub.get(f"{prefix}extraneous_f", ""),
                "extraneous_severity": sub.get(f"{prefix}extraneous_sev", ""),
                "flow": sub.get(f"{prefix}flow", ""),
                "flow_findings": sub.get(f"{prefix}flow_f", ""),
            }

        evaluations[key] = {
            "document_id": doc_id,
            "evaluator": evaluator,
            "group": sub.get("group", ""),
            "status": "completed",
            "timestamp": sub.get("timestamp", datetime.now().isoformat()),
            **model_evals,
            "preference": sub.get("preference", ""),
            "preference_reasons": sub.get("pref_reasons", ""),
            "comment_one_liner": sub.get("comment_one_liner", ""),
            "comment_visit_summary": sub.get("comment_visit_summary", ""),
        }
        count += 1

    save_evaluations(evaluations)
    return count


SEVERITY_SCORES = {"Critical": 0, "Significant": 0.33, "Minor": 0.67, "None": 1}


def _score_model(m_eval: dict) -> dict:
    """Calculate numeric scores for one model's evaluation.
    Good = 1, Bad = 0, Severity in thirds (Critical=0, Significant=0.33, Minor=0.67, None=1).
    """
    scores = {}

    # Fabrication: No = 1, Yes = 0
    scores["fab_score"] = 1 if m_eval.get("hallucination_fabrication") == "No hallucination" else 0

    # Inference: No = 1, Yes + Unsafe = 0, Yes + Safe = 1
    if m_eval.get("hallucination_inference") == "No clinical inference":
        scores["inf_score"] = 1
    elif m_eval.get("inference_breakdown") == "Unsafe, NON-Deducible Inference":
        scores["inf_score"] = 0
    else:
        scores["inf_score"] = 1

    # Omission: No = 1, Yes = severity-based
    if m_eval.get("pertinent_omission") == "No omission":
        scores["omission_score"] = 1
    else:
        scores["omission_score"] = SEVERITY_SCORES.get(m_eval.get("omission_severity", ""), 0)

    # Extraneous: No = 1, Yes = severity-based
    if m_eval.get("extraneous_info") == "No extraneous information":
        scores["extraneous_score"] = 1
    else:
        scores["extraneous_score"] = SEVERITY_SCORES.get(m_eval.get("extraneous_severity", ""), 0)

    # Flow: No = 1, Yes = 0
    scores["flow_score"] = 1 if m_eval.get("flow") == "No flow issues" else 0

    return scores


def export_all_evaluations() -> list:
    """Export all evaluations as a list of flat dicts (for CSV/XLSX export)."""
    evaluations = load_evaluations()
    rows = []

    for key, ev in evaluations.items():
        row = {
            "evaluator": ev.get("evaluator", ""),
            "document_id": ev.get("document_id", ""),
            "group": ev.get("group", ""),
            "status": ev.get("status", ""),
            "timestamp": ev.get("timestamp", ""),
        }

        for m_num in ["1", "2", "3"]:
            m_eval = ev.get(f"model_{m_num}_eval", {})
            prefix = f"m{m_num}_"
            row[f"{prefix}hall_fab"] = m_eval.get("hallucination_fabrication", "")
            row[f"{prefix}hall_fab_f"] = m_eval.get("hallucination_fabrication_findings", "")
            row[f"{prefix}hall_inf"] = m_eval.get("hallucination_inference", "")
            row[f"{prefix}inf_breakdown"] = m_eval.get("inference_breakdown", "")
            row[f"{prefix}hall_inf_f"] = m_eval.get("hallucination_inference_findings", "")
            row[f"{prefix}omission"] = m_eval.get("pertinent_omission", "")
            row[f"{prefix}omission_f"] = m_eval.get("omission_findings", "")
            row[f"{prefix}omission_sev"] = m_eval.get("omission_severity", "")
            row[f"{prefix}extraneous"] = m_eval.get("extraneous_info", "")
            row[f"{prefix}extraneous_f"] = m_eval.get("extraneous_findings", "")
            row[f"{prefix}extraneous_sev"] = m_eval.get("extraneous_severity", "")
            row[f"{prefix}flow"] = m_eval.get("flow", "")
            row[f"{prefix}flow_f"] = m_eval.get("flow_findings", "")

            # Calculated scores
            scores = _score_model(m_eval)
            for score_key, score_val in scores.items():
                row[f"{prefix}{score_key}"] = score_val

        row["preference"] = ev.get("preference", "")
        row["pref_reasons"] = ev.get("preference_reasons", "")
        rows.append(row)

    return rows
