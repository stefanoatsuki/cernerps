import streamlit as st
import pandas as pd
import json
import requests
from pathlib import Path
from datetime import datetime

from data_loader import load_evaluation_data, get_evaluator_notes, EVALUATOR_GROUPS
from evaluation_storage import (
    load_evaluations, get_evaluation, save_progress, submit_evaluation,
    get_evaluator_progress, get_note_status, get_all_progress,
    rebuild_from_submissions, export_all_evaluations, make_key,
)

# ───────────────────────── Configuration ─────────────────────────

st.set_page_config(page_title="Patient Summary Evaluation", layout="wide")

CSS_PATH = Path(__file__).parent / "style.css"
if CSS_PATH.exists():
    st.markdown(f"<style>{CSS_PATH.read_text()}</style>", unsafe_allow_html=True)

# ───────────────────────── Constants ─────────────────────────────

EVALUATOR_PASSWORDS = dict(st.secrets.get("passwords", {
    "Evaluator 1": "PVS-eval-alpha-7291",
    "Evaluator 2": "PVS-eval-beta-4638",
    "Evaluator 3": "PVS-eval-gamma-8154",
    "Evaluator 4": "PVS-eval-delta-3927",
    "Evaluator 5": "PVS-eval-epsilon-6482",
    "Evaluator 6": "PVS-eval-zeta-1795",
    "Tester": "PVS-test-preview-2025",
}))
ADMIN_PASSWORD = st.secrets.get("admin_password", "PVS-admin-dashboard-2025")
GOOGLE_SHEETS_URL = st.secrets.get("google_sheets_url", "")

INF_BREAKDOWN_OPTIONS = [
    "Safe, Deducible Inference",
    "Unsafe, NON-Deducible Inference",
    "Safe, NON-Deducible Inference",
]
OMISSION_SEVERITY_OPTIONS = ["Critical", "Significant", "Minor", "None"]
EXTRANEOUS_SEVERITY_OPTIONS = ["Critical", "Significant", "Minor", "None"]
PREFERENCE_OPTIONS = ["Model 1", "Model 2", "Model 3"]

STEP_LABELS = {1: "Model 1", 2: "Model 2", 3: "Model 3", 4: "Preference"}
STEP_COLORS = {1: "#3B82F6", 2: "#8B5CF6", 3: "#10B981", 4: "#F59E0B"}

INSTRUCTIONS_DOC_URL = "https://docs.google.com/document/d/1_pQP5FPWJ5QsKPwqBIBTYDr1R4FynkGcYCTpYPSw5vw/edit?usp=sharing"

INSTRUCTIONS_MD = """
**For each note you will:**
1. Open the original clinical note (PDF link provided)
2. Score each of the 3 model summaries on 5 metrics
3. Pick your preferred model and explain why

---

**Metric 1 — Hallucination (Fabrication)**
Is there information in the summary that is **completely invented** — not found anywhere in the source note?
- *If Yes:* copy/paste the fabricated text

**Metric 2 — Hallucination (Inference)**
Does the summary contain information **logically derived but not explicitly stated** in the source?
- *If Yes:* select the inference type:
  - **Safe, Deducible** — logically certain (e.g. "Amoxicillin" → "antibiotics") = PASS
  - **Unsafe, NON-Deducible** — harmful leap without evidence = FAIL
  - **Safe, NON-Deducible** — minor interpretation, no clinical impact = PASS
- *If Yes:* copy/paste the inferred text + context

**Metric 3 — Pertinent Omission (Recall)**
Is **key clinical information missing** that would affect a reader's understanding?
- *If Yes:* describe what's missing and select severity:
  - **Critical** — dangerously incomplete picture
  - **Significant** — would change reader's next action
  - **Minor** — missed but reader can still act appropriately
- *NOT omissions:* med dosages, PE findings (unless they drove the plan), follow-up dates, stable background conditions

**Metric 4 — Extraneous Information (Precision)**
Does the summary include **accurate but unnecessary** information?
- *If Yes:* classify as Rule violation / Low-value / Profile bleed, and select severity:
  - **Critical** — obscures the clinical core
  - **Significant** — distracts but understandable with effort
  - **Minor** — present but reader still gets complete picture

**Metric 5 — Flow & Format (Coherence)**
Is content **accurate but poorly expressed?** (bad grouping, confusing syntax, poor progression, redundancy)
- Only flag if the content itself is correct. Factual errors = Hallucination, not Flow.

---

**Overall Preference**
Which model's summary would be **most useful to a clinician?** Pick one and explain why.
"""

# ───────────────────────── Session State ─────────────────────────

def init_session_state():
    defaults = {
        "screen": 0, "evaluator": None, "is_admin": False, "login_error": False,
        "df": None, "selected_note_idx": None, "auto_recovery_attempted": False,
        "wizard_step": 1,
        "eval_form_data": {},
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session_state()

# ───────────────────────── Data Loading ──────────────────────────

@st.cache_data(show_spinner=False)
def load_data():
    return load_evaluation_data()

def ensure_data():
    if st.session_state.df is None:
        st.session_state.df = load_data()

# ───────────────────────── Google Sheets ─────────────────────────

def submit_to_google_sheets(form_data: dict) -> bool:
    if not GOOGLE_SHEETS_URL:
        return False
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r = requests.post(GOOGLE_SHEETS_URL, data=json.dumps(form_data),
                          timeout=10, verify=False, headers={"Content-Type": "application/json"})
        return r.status_code == 200
    except Exception:
        return False

def attempt_auto_recovery():
    if st.session_state.auto_recovery_attempted or not GOOGLE_SHEETS_URL:
        return
    st.session_state.auto_recovery_attempted = True
    evaluations = load_evaluations()
    if evaluations:
        return
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r = requests.get(GOOGLE_SHEETS_URL, verify=False, timeout=10)
        if r.status_code == 200:
            subs = r.json()
            if isinstance(subs, list) and subs:
                rebuild_from_submissions(subs)
    except Exception:
        pass

# ───────────────────────── Validation ────────────────────────────

def validate_evaluation(d: dict) -> list:
    errors = []
    for m_num in ["1", "2", "3"]:
        m = d.get(f"model_{m_num}_eval", {})
        L = f"Model {m_num}"
        if not m.get("hallucination_fabrication"):
            errors.append(f"{L}: Hallucination-Fabrication selection required")
        elif m["hallucination_fabrication"] == "Yes hallucination":
            if not m.get("hallucination_fabrication_findings", "").strip():
                errors.append(f"{L}: Fabrication findings required when 'Yes' selected")
        if not m.get("hallucination_inference"):
            errors.append(f"{L}: Hallucination-Inference selection required")
        elif m["hallucination_inference"] == "Yes clinical inference":
            if not m.get("inference_breakdown"):
                errors.append(f"{L}: Inference Breakdown required when 'Yes' selected")
            if not m.get("hallucination_inference_findings", "").strip():
                errors.append(f"{L}: Inference findings required when 'Yes' selected")
        if not m.get("pertinent_omission"):
            errors.append(f"{L}: Pertinent Omission selection required")
        elif m["pertinent_omission"] == "Yes omission":
            if not m.get("omission_findings", "").strip():
                errors.append(f"{L}: Omission findings required when 'Yes' selected")
            if not m.get("omission_severity"):
                errors.append(f"{L}: Omission severity required when 'Yes' selected")
        if not m.get("extraneous_info"):
            errors.append(f"{L}: Extraneous Information selection required")
        elif m["extraneous_info"] == "Yes extraneous information":
            if not m.get("extraneous_findings", "").strip():
                errors.append(f"{L}: Extraneous findings required when 'Yes' selected")
            if not m.get("extraneous_severity"):
                errors.append(f"{L}: Extraneous severity required when 'Yes' selected")
        if not m.get("flow"):
            errors.append(f"{L}: Flow selection required")
        elif m["flow"] == "Yes flow issues":
            if not m.get("flow_findings", "").strip():
                errors.append(f"{L}: Flow findings required when 'Yes' selected")
    if not d.get("preference"):
        errors.append("Overall Preference selection required")
    if not d.get("preference_reasons", "").strip():
        errors.append("Preference justification is required")
    return errors

# ───────────────────────── Sheets Payload ────────────────────────

def build_sheets_payload(note_info: dict, d: dict) -> dict:
    p = {
        "documentId": note_info["document_id"],
        "noteType": note_info.get("note_type", ""),
        "readerSpecialty": note_info.get("reader_specialty", ""),
        "evaluator": "TEST" if st.session_state.evaluator == "Tester" else st.session_state.evaluator,
        "group": EVALUATOR_GROUPS.get(st.session_state.evaluator, ""),
    }
    for m_num, prefix in [("1", "m1_"), ("2", "m2_"), ("3", "m3_")]:
        m = d.get(f"model_{m_num}_eval", {})
        p[f"{prefix}hall_fab"] = m.get("hallucination_fabrication", "")
        p[f"{prefix}hall_fab_f"] = m.get("hallucination_fabrication_findings", "")
        p[f"{prefix}hall_inf"] = m.get("hallucination_inference", "")
        p[f"{prefix}inf_breakdown"] = m.get("inference_breakdown", "")
        p[f"{prefix}hall_inf_f"] = m.get("hallucination_inference_findings", "")
        p[f"{prefix}omission"] = m.get("pertinent_omission", "")
        p[f"{prefix}omission_f"] = m.get("omission_findings", "")
        p[f"{prefix}omission_sev"] = m.get("omission_severity", "")
        p[f"{prefix}extraneous"] = m.get("extraneous_info", "")
        p[f"{prefix}extraneous_f"] = m.get("extraneous_findings", "")
        p[f"{prefix}extraneous_sev"] = m.get("extraneous_severity", "")
        p[f"{prefix}flow"] = m.get("flow", "")
        p[f"{prefix}flow_f"] = m.get("flow_findings", "")
    p["preference"] = d.get("preference", "")
    p["pref_reasons"] = d.get("preference_reasons", "")
    p["comment_one_liner"] = d.get("comment_one_liner", "")
    p["comment_visit_summary"] = d.get("comment_visit_summary", "")
    return p


# ───────────────────────── Wizard Helpers ────────────────────────

def _capture_step():
    """Save current wizard step's widget values into eval_form_data."""
    step = st.session_state.wizard_step
    fd = st.session_state.eval_form_data
    if step in (1, 2, 3):
        m = step
        fd[f"model_{m}_eval"] = {
            "hallucination_fabrication": st.session_state.get(f"m{m}_hall_fab"),
            "hallucination_fabrication_findings": st.session_state.get(f"m{m}_hall_fab_f", ""),
            "hallucination_inference": st.session_state.get(f"m{m}_hall_inf"),
            "inference_breakdown": st.session_state.get(f"m{m}_inf_bd"),
            "hallucination_inference_findings": st.session_state.get(f"m{m}_hall_inf_f", ""),
            "pertinent_omission": st.session_state.get(f"m{m}_omission"),
            "omission_findings": st.session_state.get(f"m{m}_omission_f", ""),
            "omission_severity": st.session_state.get(f"m{m}_omission_sev"),
            "extraneous_info": st.session_state.get(f"m{m}_extraneous"),
            "extraneous_findings": st.session_state.get(f"m{m}_extraneous_f", ""),
            "extraneous_severity": st.session_state.get(f"m{m}_extraneous_sev"),
            "flow": st.session_state.get(f"m{m}_flow"),
            "flow_findings": st.session_state.get(f"m{m}_flow_f", ""),
        }
    elif step == 4:
        fd["preference"] = st.session_state.get("preference_radio")
        fd["preference_reasons"] = st.session_state.get("pref_reasons", "")
        fd["comment_one_liner"] = st.session_state.get("comment_one_liner", "")
        fd["comment_visit_summary"] = st.session_state.get("comment_visit_summary", "")

def _go_next():
    _capture_step()
    st.session_state.wizard_step = min(st.session_state.wizard_step + 1, 4)

def _go_back():
    _capture_step()
    st.session_state.wizard_step = max(st.session_state.wizard_step - 1, 1)

def _jump_to(step):
    _capture_step()
    st.session_state.wizard_step = step

def _collect_all(existing_eval: dict) -> dict:
    """Collect all form data. Active step reads widgets; others read eval_form_data."""
    fd = st.session_state.eval_form_data
    step = st.session_state.wizard_step
    result = {}
    for m in (1, 2, 3):
        if step == m:
            result[f"model_{m}_eval"] = {
                "hallucination_fabrication": st.session_state.get(f"m{m}_hall_fab"),
                "hallucination_fabrication_findings": st.session_state.get(f"m{m}_hall_fab_f", ""),
                "hallucination_inference": st.session_state.get(f"m{m}_hall_inf"),
                "inference_breakdown": st.session_state.get(f"m{m}_inf_bd"),
                "hallucination_inference_findings": st.session_state.get(f"m{m}_hall_inf_f", ""),
                "pertinent_omission": st.session_state.get(f"m{m}_omission"),
                "omission_findings": st.session_state.get(f"m{m}_omission_f", ""),
                "omission_severity": st.session_state.get(f"m{m}_omission_sev"),
                "extraneous_info": st.session_state.get(f"m{m}_extraneous"),
                "extraneous_findings": st.session_state.get(f"m{m}_extraneous_f", ""),
                "extraneous_severity": st.session_state.get(f"m{m}_extraneous_sev"),
                "flow": st.session_state.get(f"m{m}_flow"),
                "flow_findings": st.session_state.get(f"m{m}_flow_f", ""),
            }
        elif f"model_{m}_eval" in fd:
            result[f"model_{m}_eval"] = fd[f"model_{m}_eval"]
        else:
            result[f"model_{m}_eval"] = existing_eval.get(f"model_{m}_eval", {})
    if step == 4:
        result["preference"] = st.session_state.get("preference_radio")
        result["preference_reasons"] = st.session_state.get("pref_reasons", "")
        result["comment_one_liner"] = st.session_state.get("comment_one_liner", "")
        result["comment_visit_summary"] = st.session_state.get("comment_visit_summary", "")
    else:
        result["preference"] = fd.get("preference", existing_eval.get("preference"))
        result["preference_reasons"] = fd.get("preference_reasons", existing_eval.get("preference_reasons", ""))
        result["comment_one_liner"] = fd.get("comment_one_liner", existing_eval.get("comment_one_liner", ""))
        result["comment_visit_summary"] = fd.get("comment_visit_summary", existing_eval.get("comment_visit_summary", ""))
    return result

def _get_index(options, value, default=0):
    return options.index(value) if value in options else default

# ───────────────────────── Step Indicator ────────────────────────

def _render_step_indicator(current_step):
    parts = []
    for i in range(1, 5):
        if i < current_step:
            cls = "done"
            circ = "&#10003;"
        elif i == current_step:
            cls = "active"
            circ = str(i)
        else:
            cls = "future"
            circ = str(i)
        parts.append(f"""
        <div class='step-wrapper'>
            <div class='step-circle {cls}'>{circ}</div>
            <div class='step-label {cls}'>{STEP_LABELS[i]}</div>
        </div>""")
        if i < 4:
            line_cls = "done" if i < current_step else "future"
            parts.append(f"<div class='step-line {line_cls}'></div>")

    st.markdown(f"<div class='step-bar'>{''.join(parts)}</div>", unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════
#  SCREEN 0: Welcome
# ═════════════════════════════════════════════════════════════════

def screen0_welcome():
    st.markdown("""
    <div class='welcome-container'>
        <div class='welcome-title'>Patient Summary Evaluation</div>
        <div class='welcome-subtitle'>
            Evaluate LLM-generated patient visit summaries across 5 clinical metrics.<br>
            Each note has 3 model outputs. You'll score them one at a time, then pick your favorite.
        </div>
    </div>
    """, unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 1, 1])
    with c2:
        if st.button("Get Started", type="primary", use_container_width=True):
            st.session_state.screen = 1
            st.rerun()

# ═════════════════════════════════════════════════════════════════
#  SCREEN 1: Login
# ═════════════════════════════════════════════════════════════════

def screen1_login():
    st.markdown("### Evaluator Login")
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        selected = st.selectbox("Choose your evaluator:", list(EVALUATOR_PASSWORDS.keys()))
        password = st.text_input("Enter your access code:", type="password")
        if st.session_state.login_error:
            st.error("Incorrect access code.")
            st.session_state.login_error = False
        if st.button("Login", type="primary", use_container_width=True):
            if password == ADMIN_PASSWORD:
                st.session_state.is_admin = True
                st.session_state.screen = 99
                st.rerun()
            elif password == EVALUATOR_PASSWORDS.get(selected, ""):
                st.session_state.evaluator = selected
                st.session_state.is_admin = False
                st.session_state.screen = 2
                st.rerun()
            else:
                st.session_state.login_error = True
                st.rerun()
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Back to Welcome", use_container_width=True):
            st.session_state.screen = 0
            st.rerun()


# ═════════════════════════════════════════════════════════════════
#  SCREEN 2: Note Queue
# ═════════════════════════════════════════════════════════════════

def screen2_note_queue():
    ensure_data()
    df = st.session_state.df
    evaluator = st.session_state.evaluator
    group = EVALUATOR_GROUPS.get(evaluator, "")
    notes = get_evaluator_notes(evaluator, df)
    if not notes:
        st.error("No notes assigned.")
        return

    doc_ids = [n["document_id"] for n in notes]
    progress = get_evaluator_progress(evaluator, doc_ids)
    total, completed = progress["total"], progress["completed"]
    pct = int(completed / total * 100) if total else 0

    col_instr, col_notes = st.columns([1, 1.3])

    # ── Left: Instructions ──
    with col_instr:
        st.markdown(f"""
        <div style='background:{STEP_COLORS[4]}18; border-left:4px solid {STEP_COLORS[4]};
                    padding:10px 16px; border-radius:8px; margin-bottom:6px;'>
            <div style='font-size:1.3em; font-weight:700; color:#E0E0E0;'>Evaluation Instructions</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(f"""
        <a href='{INSTRUCTIONS_DOC_URL}' target='_blank' style='
            display:block; text-align:center; background:linear-gradient(135deg,#2C5282,#3B6BA5);
            color:#FFF; padding:10px 16px; border-radius:8px; font-weight:700; font-size:14px;
            text-decoration:none; margin-bottom:6px; letter-spacing:0.3px;
        '>OPEN FULL INSTRUCTIONS (Google Doc)</a>
        """, unsafe_allow_html=True)
        with st.container(height=550, border=True):
            st.markdown(INSTRUCTIONS_MD)

    # ── Right: Note list ──
    with col_notes:
        st.markdown(f"### {evaluator} — Group {group}")
        st.markdown(f"""
        <div class='progress-bar-container'><div class='progress-bar-fill' style='width:{pct}%;'></div></div>
        <div style='color:#8A8A8A; font-size:13px; margin:4px 0 12px 0;'>{completed} of {total} completed</div>
        """, unsafe_allow_html=True)

        # Next up CTA
        next_idx = None
        for i, n in enumerate(notes):
            if get_note_status(evaluator, n["document_id"]) != "completed":
                next_idx = i
                break

        if next_idx is not None:
            ns = get_note_status(evaluator, notes[next_idx]["document_id"])
            label = "Continue Evaluation" if ns == "in_progress" else "Start Next Note"
            if st.button(label, type="primary", use_container_width=True, key="cta"):
                st.session_state.selected_note_idx = next_idx
                st.session_state.wizard_step = 1
                st.session_state.eval_form_data = {}
                st.session_state.screen = 3
                st.rerun()
        elif completed == total:
            st.success("All notes completed!")

        # Note list in scroll box
        with st.container(height=460, border=True):
            for idx, note in enumerate(notes):
                doc_id = note["document_id"]
                status = get_note_status(evaluator, doc_id)

                if status == "completed":
                    dot_color = "#34C759"
                elif status == "in_progress":
                    dot_color = "#F59E0B"
                else:
                    dot_color = "#4A4A4A"

                c1, c2 = st.columns([4, 1])
                with c1:
                    st.markdown(
                        f"<div style='padding:4px 0;'>"
                        f"<span style='display:inline-block; width:10px; height:10px; border-radius:50%; background:{dot_color}; margin-right:12px; vertical-align:middle;'></span>"
                        f"<span style='color:#6A6A6A; margin-right:8px;'>{idx+1}.</span>"
                        f"<span style='font-weight:600;'>{doc_id}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                with c2:
                    lbl = "Review" if status == "completed" else ("Continue" if status == "in_progress" else "Open")
                    if st.button(lbl, key=f"n{idx}", use_container_width=True):
                        st.session_state.selected_note_idx = idx
                        st.session_state.wizard_step = 1
                        st.session_state.eval_form_data = {}
                        st.session_state.screen = 3
                        st.rerun()

        if st.button("Logout"):
            st.session_state.evaluator = None
            st.session_state.screen = 0
            st.rerun()


# ═════════════════════════════════════════════════════════════════
#  SCREEN 3: Evaluation Wizard  (gmk-style)
# ═════════════════════════════════════════════════════════════════

def screen3_evaluation():
    ensure_data()
    df = st.session_state.df
    evaluator = st.session_state.evaluator
    group = EVALUATOR_GROUPS.get(evaluator, "")
    notes = get_evaluator_notes(evaluator, df)

    if st.session_state.selected_note_idx is None or st.session_state.selected_note_idx >= len(notes):
        st.session_state.screen = 2
        st.rerun()
        return

    idx = st.session_state.selected_note_idx
    note = notes[idx]
    doc_id = note["document_id"]
    note_type = note.get("note_type", "").replace("_", " ").title()
    specialty = note.get("reader_specialty", "")
    gdrive_url = note.get("gdrive_url", "")
    step = st.session_state.wizard_step

    existing_eval = get_evaluation(evaluator, doc_id, group)
    fd = st.session_state.eval_form_data

    # ── Top nav ──
    n1, n2, n3 = st.columns([1, 2, 1])
    with n1:
        if st.button("← Back to Notes"):
            st.session_state.screen = 2
            st.rerun()
    with n3:
        st.markdown(f"<div style='text-align:right; color:#8A8A8A; padding-top:8px;'>Note {idx+1} of {len(notes)}</div>", unsafe_allow_html=True)

    # ── Context bar ──
    st.markdown(f"""
    <div class='context-bar'>
        <div><div class='ctx-label'>Document ID</div><div class='ctx-value'>{doc_id}</div></div>
        <div><div class='ctx-label'>Note Type</div><div class='ctx-value'>{note_type}</div></div>
        <div><div class='ctx-label'>Specialty</div><div class='ctx-value'>{specialty}</div></div>
    </div>
    """, unsafe_allow_html=True)

    # ── Instructions reference ──
    with st.expander("View Evaluation Instructions"):
        st.markdown(f"[Open Full Instructions (Google Doc)]({INSTRUCTIONS_DOC_URL})")
        st.markdown(INSTRUCTIONS_MD)

    # ── Step indicator ──
    _render_step_indicator(step)

    summaries = {
        1: note.get("model_1_summary", ""),
        2: note.get("model_2_summary", ""),
        3: note.get("model_3_summary", ""),
    }

    # ── Source note (big, obvious — right above model content) ──
    if gdrive_url:
        st.markdown(f"""
        <a href='{gdrive_url}' target='_blank' style='
            display:block; text-align:center; background:linear-gradient(135deg,#2C5282,#3B6BA5);
            color:#FFF; padding:14px 24px; border-radius:10px; font-weight:700; font-size:16px;
            text-decoration:none; margin-bottom:10px; letter-spacing:0.5px;
        '>OPEN ORIGINAL CLINICAL NOTE</a>
        """, unsafe_allow_html=True)

    # ═══ STEPS 1-3: Score one model — summary left, form right ═══

    if step in (1, 2, 3):
        m = step
        m_key = f"model_{m}_eval"
        ex = fd.get(m_key, existing_eval.get(m_key, {}))
        color = STEP_COLORS[m]

        col_summary, col_eval = st.columns([1, 1.2])

        # ── Left: Model summary in scroll box ──
        with col_summary:
            st.markdown(f"""
            <div style='background:{color}18; border-left:4px solid {color};
                        padding:12px 18px; border-radius:8px; margin-bottom:6px;'>
                <div style='font-size:2em; font-weight:800; color:{color}; line-height:1.1;'>MODEL {m}</div>
                <div style='font-size:12px; color:#8A8A8A; margin-top:2px;'>Summary Output</div>
            </div>
            """, unsafe_allow_html=True)
            with st.container(height=520, border=True):
                st.markdown(summaries[m])

        # ── Right: Evaluation form in scroll box ──
        with col_eval:
            st.markdown(f"""
            <div style='background:#2A2A2A; border-left:4px solid {color};
                        padding:12px 18px; border-radius:8px; margin-bottom:6px;'>
                <div style='font-size:1.3em; font-weight:700; color:#E0E0E0; line-height:1.1;'>Score Model {m}</div>
                <div style='font-size:12px; color:#8A8A8A; margin-top:2px;'>Step {m} of 4 &middot; 5 metrics</div>
            </div>
            """, unsafe_allow_html=True)
            with st.container(height=520, border=True):

                # ── Metric 1: Fabrication ──
                with st.container(border=True):
                    st.markdown("**1 · Hallucination — Fabrication**")
                    st.caption("Information completely invented — not in the source note?")
                    fab_val = ex.get("hallucination_fabrication") or "No hallucination"
                    fab_idx = 0 if fab_val == "No hallucination" else 1
                    st.radio("fab", ["No hallucination", "Yes hallucination"],
                             index=fab_idx, key=f"m{m}_hall_fab", horizontal=True,
                             label_visibility="collapsed")
                    if st.session_state.get(f"m{m}_hall_fab") == "Yes hallucination":
                        st.text_area("fab_f",
                                     value=ex.get("hallucination_fabrication_findings", ""),
                                     key=f"m{m}_hall_fab_f", height=60,
                                     label_visibility="collapsed",
                                     placeholder="Copy/paste fabricated text from summary…")

                # ── Metric 2: Inference ──
                with st.container(border=True):
                    st.markdown("**2 · Hallucination — Inference**")
                    st.caption("Logically derived but not explicitly stated in source?")
                    inf_val = ex.get("hallucination_inference") or "No clinical inference"
                    inf_idx = 0 if inf_val == "No clinical inference" else 1
                    st.radio("inf", ["No clinical inference", "Yes clinical inference"],
                             index=inf_idx, key=f"m{m}_hall_inf", horizontal=True,
                             label_visibility="collapsed")
                    if st.session_state.get(f"m{m}_hall_inf") == "Yes clinical inference":
                        bd_idx = _get_index(INF_BREAKDOWN_OPTIONS, ex.get("inference_breakdown"), 0)
                        st.selectbox("Inference type", INF_BREAKDOWN_OPTIONS,
                                     index=bd_idx, key=f"m{m}_inf_bd")
                        st.text_area("inf_f",
                                     value=ex.get("hallucination_inference_findings", ""),
                                     key=f"m{m}_hall_inf_f", height=60,
                                     label_visibility="collapsed",
                                     placeholder="Copy/paste inferred text + context…")

                # ── Metric 3: Omission ──
                with st.container(border=True):
                    st.markdown("**3 · Pertinent Omission (Recall)**")
                    st.caption("Key clinical information missing from the summary?")
                    om_val = ex.get("pertinent_omission") or "No omission"
                    om_idx = 0 if om_val == "No omission" else 1
                    st.radio("om", ["No omission", "Yes omission"],
                             index=om_idx, key=f"m{m}_omission", horizontal=True,
                             label_visibility="collapsed")
                    if st.session_state.get(f"m{m}_omission") == "Yes omission":
                        st.text_area("om_f",
                                     value=ex.get("omission_findings", ""),
                                     key=f"m{m}_omission_f", height=60,
                                     label_visibility="collapsed",
                                     placeholder="What's missing and why does it matter?")
                        sv_idx = _get_index(OMISSION_SEVERITY_OPTIONS, ex.get("omission_severity"), 0)
                        st.selectbox("Severity", OMISSION_SEVERITY_OPTIONS,
                                     index=sv_idx, key=f"m{m}_omission_sev")

                # ── Metric 4: Extraneous ──
                with st.container(border=True):
                    st.markdown("**4 · Extraneous Information (Precision)**")
                    st.caption("Accurate but unnecessary? (Rule violation / Low-value / Profile bleed)")
                    ext_val = ex.get("extraneous_info") or "No extraneous information"
                    ext_idx = 0 if ext_val == "No extraneous information" else 1
                    st.radio("ext", ["No extraneous information", "Yes extraneous information"],
                             index=ext_idx, key=f"m{m}_extraneous", horizontal=True,
                             label_visibility="collapsed")
                    if st.session_state.get(f"m{m}_extraneous") == "Yes extraneous information":
                        st.text_area("ext_f",
                                     value=ex.get("extraneous_findings", ""),
                                     key=f"m{m}_extraneous_f", height=60,
                                     label_visibility="collapsed",
                                     placeholder="Rule violation / Low-value / Profile bleed…")
                        es_idx = _get_index(EXTRANEOUS_SEVERITY_OPTIONS, ex.get("extraneous_severity"), 0)
                        st.selectbox("Severity", EXTRANEOUS_SEVERITY_OPTIONS,
                                     index=es_idx, key=f"m{m}_extraneous_sev")

                # ── Metric 5: Flow ──
                with st.container(border=True):
                    st.markdown("**5 · Flow & Format (Coherence)**")
                    st.caption("Poorly expressed? (grouping, syntax, progression, redundancy)")
                    fl_val = ex.get("flow") or "No flow issues"
                    fl_idx = 0 if fl_val == "No flow issues" else 1
                    st.radio("fl", ["No flow issues", "Yes flow issues"],
                             index=fl_idx, key=f"m{m}_flow", horizontal=True,
                             label_visibility="collapsed")
                    if st.session_state.get(f"m{m}_flow") == "Yes flow issues":
                        st.text_area("fl_f",
                                     value=ex.get("flow_findings", ""),
                                     key=f"m{m}_flow_f", height=60,
                                     label_visibility="collapsed",
                                     placeholder="Describe the flow/format issues…")

    # ═══ STEP 4: Preference — all 3 summaries side-by-side ═══

    elif step == 4:
        st.markdown(f"""
        <div style='background:rgba(245,158,11,0.1); border-left:4px solid #F59E0B;
                    padding:12px 18px; border-radius:8px; margin-bottom:6px;'>
            <div style='font-size:1.8em; font-weight:800; color:#F59E0B; line-height:1.1;'>PICK YOUR PREFERRED MODEL</div>
            <div style='font-size:12px; color:#8A8A8A; margin-top:2px;'>Step 4 of 4 &middot; Compare all three and choose</div>
        </div>
        """, unsafe_allow_html=True)

        sc1, sc2, sc3 = st.columns(3)
        for col, m_num, clr in [(sc1, 1, STEP_COLORS[1]), (sc2, 2, STEP_COLORS[2]), (sc3, 3, STEP_COLORS[3])]:
            with col:
                st.markdown(f"<div style='text-align:center; font-weight:700; color:{clr}; font-size:1.1em; margin-bottom:4px;'>Model {m_num}</div>", unsafe_allow_html=True)
                with st.container(height=300, border=True):
                    st.markdown(summaries[m_num])

        pref_ex = {
            "preference": fd.get("preference", existing_eval.get("preference")),
            "preference_reasons": fd.get("preference_reasons", existing_eval.get("preference_reasons", "")),
        }

        with st.container(border=True):
            st.markdown("**Which model produced the best summary?**")
            pref_idx = _get_index(PREFERENCE_OPTIONS, pref_ex.get("preference"), 0)
            st.radio("pref", PREFERENCE_OPTIONS, index=pref_idx,
                     key="preference_radio", horizontal=True,
                     label_visibility="collapsed")
            st.markdown("**Why is this model's summary the best?** *(required)*")
            st.text_area("reasons",
                         value=pref_ex.get("preference_reasons", ""),
                         key="pref_reasons", height=80,
                         label_visibility="collapsed",
                         placeholder="Explain your reasoning…")

    # ═══ NAVIGATION ═══

    nav1, nav2, nav3 = st.columns([1, 1, 1])

    with nav1:
        if step > 1:
            st.button("← Back", on_click=_go_back, use_container_width=True)
        else:
            if st.button("Save Progress", use_container_width=True):
                full = _collect_all(existing_eval)
                save_progress(evaluator, doc_id, group, full)
                st.toast("Progress saved")

    with nav2:
        if step > 1:
            if st.button("Save Progress", use_container_width=True, key="save_mid"):
                full = _collect_all(existing_eval)
                save_progress(evaluator, doc_id, group, full)
                st.toast("Progress saved")

    with nav3:
        if step < 4:
            next_label = f"Next → Score Model {step + 1}" if step < 3 else "Next → Pick Preference"
            st.button(next_label, type="primary", on_click=_go_next, use_container_width=True)
        else:
            if st.button("Submit & Next Note →", type="primary", use_container_width=True):
                full = _collect_all(existing_eval)
                errors = validate_evaluation(full)
                if errors:
                    for e in errors:
                        st.error(e)
                else:
                    submit_evaluation(evaluator, doc_id, group, full)
                    payload = build_sheets_payload(note, full)
                    sheets_ok = submit_to_google_sheets(payload)
                    if GOOGLE_SHEETS_URL and not sheets_ok:
                        st.warning("Saved locally but Google Sheets sync failed.")
                    st.toast("Evaluation submitted!")
                    if idx + 1 < len(notes):
                        st.session_state.selected_note_idx = idx + 1
                        st.session_state.wizard_step = 1
                        st.session_state.eval_form_data = {}
                    else:
                        st.session_state.screen = 2
                        st.session_state.selected_note_idx = None
                    st.rerun()


# ═════════════════════════════════════════════════════════════════
#  SCREEN 99: Admin Dashboard
# ═════════════════════════════════════════════════════════════════

def screen99_admin():
    ensure_data()
    st.markdown("### Admin Dashboard")
    if st.button("Logout"):
        st.session_state.is_admin = False
        st.session_state.screen = 0
        st.rerun()

    all_progress = get_all_progress()
    total_submissions = sum(p["completed"] for p in all_progress.values())
    total_in_progress = sum(p["in_progress"] for p in all_progress.values())

    mc1, mc2, mc3 = st.columns(3)
    with mc1:
        st.markdown(f"<div class='admin-metric-card'><div class='metric-value'>{total_submissions}</div><div class='metric-label'>Completed</div></div>", unsafe_allow_html=True)
    with mc2:
        st.markdown(f"<div class='admin-metric-card'><div class='metric-value'>{total_in_progress}</div><div class='metric-label'>In Progress</div></div>", unsafe_allow_html=True)
    with mc3:
        st.markdown(f"<div class='admin-metric-card'><div class='metric-value'>{total_submissions}/200</div><div class='metric-label'>Total</div></div>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### Evaluator Progress")
    df = st.session_state.df
    for gn, evs in [("Group A", ["Evaluator 1", "Evaluator 2"]),
                     ("Group B", ["Evaluator 3", "Evaluator 4"]),
                     ("Group C", ["Evaluator 5", "Evaluator 6"])]:
        st.markdown(f"**{gn}**")
        for ev in evs:
            ns = get_evaluator_notes(ev, df)
            ids = [n["document_id"] for n in ns]
            pg = get_evaluator_progress(ev, ids)
            t, c = pg["total"], pg["completed"]
            pct = int(c / t * 100) if t else 0
            e1, e2 = st.columns([3, 1])
            with e1:
                st.markdown(f"<div style='margin-bottom:8px;'><span style='font-weight:600;'>{ev}</span><div class='progress-bar-container'><div class='progress-bar-fill' style='width:{pct}%;'></div></div></div>", unsafe_allow_html=True)
            with e2:
                st.markdown(f"<div style='text-align:right; color:#8A8A8A;'>{c}/{t} ({pct}%)</div>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### Export")
    if st.button("Export All Evaluations as CSV"):
        rows = export_all_evaluations()
        if rows:
            csv = pd.DataFrame(rows).to_csv(index=False)
            st.download_button("Download CSV", csv, "pvs_evaluations_export.csv", "text/csv")
        else:
            st.info("No evaluations yet.")

    st.markdown("---")
    st.markdown("#### Recovery")
    if GOOGLE_SHEETS_URL:
        if st.button("Pull from Google Sheets"):
            try:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                r = requests.get(GOOGLE_SHEETS_URL, verify=False, timeout=15)
                if r.status_code == 200:
                    count = rebuild_from_submissions(r.json())
                    st.success(f"Recovered {count} submissions")
                    st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")
    else:
        st.info("Google Sheets URL not configured.")

    import io
    up = st.file_uploader("Upload CSV for recovery", type=["csv"])
    if up:
        subs = pd.read_csv(io.StringIO(up.read().decode("utf-8"))).to_dict("records")
        count = rebuild_from_submissions(subs)
        st.success(f"Recovered {count} submissions")
        st.rerun()


# ═════════════════════════════════════════════════════════════════
#  Main Router
# ═════════════════════════════════════════════════════════════════

def main():
    attempt_auto_recovery()
    s = st.session_state.screen
    if s == 0: screen0_welcome()
    elif s == 1: screen1_login()
    elif s == 2:
        if not st.session_state.evaluator:
            st.session_state.screen = 1; st.rerun()
        else: screen2_note_queue()
    elif s == 3:
        if not st.session_state.evaluator:
            st.session_state.screen = 1; st.rerun()
        else: screen3_evaluation()
    elif s == 99:
        if not st.session_state.is_admin:
            st.session_state.screen = 1; st.rerun()
        else: screen99_admin()
    else:
        st.session_state.screen = 0; st.rerun()

if __name__ == "__main__":
    main()
