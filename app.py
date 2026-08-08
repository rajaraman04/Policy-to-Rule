import os
try:  # load a local .env file if python-dotenv is installed
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import pandas as pd
import streamlit as st

import engine

st.set_page_config(page_title="Policy-to-Rule", page_icon="🩺", layout="wide")

# sidebar
with st.sidebar:
    st.title("🩺 Policy-to-Rule")
    st.caption("Written billing policy → executable payment-integrity check")

    have_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if have_key:
        st.success(f"Live AI mode\n\nmodel: `{engine.DEFAULT_MODEL}`")
    else:
        st.warning("Offline demo mode\n\n(no ANTHROPIC_API_KEY — using cached rules)")

    st.markdown(
        "**How it works**\n\n"
        "1. An LLM *translates* English policy into a structured rule "
        "using a fixed vocabulary of fields + operators.\n"
        "2. A deterministic Python engine *decides* which claims are flagged.\n\n"
        "The AI never decides a claim on its own — every flag is auditable."
    )

#state + data
if "rule" not in st.session_state:
    st.session_state.rule = None
    st.session_state.rule_source = None

claims = engine.load_claims()
claims_df = pd.DataFrame(claims)
samples = engine.list_sample_policies()

tab1, tab2, tab3 = st.tabs(["1 · Policy → Rule", "2 · Run on claims", "3 · Compare versions"])

#Tab 1: convert
with tab1:
    st.subheader("Convert a written policy into an executable rule")
    col_a, col_b = st.columns(2)

    with col_a:
        choice = st.selectbox("Load a sample policy", samples, index=0)
        policy_text = st.text_area("Policy text (editable)", engine.load_sample_policy(choice), height=280)
        go = st.button("⚙️  Convert to rule", type="primary")

    with col_b:
        if go:
            try:
                rule, source = engine.policy_to_rule(policy_text, sample_stem=choice)
                st.session_state.rule = rule
                st.session_state.rule_source = source
            except Exception as exc:
                st.error(str(exc))

        if st.session_state.rule:
            badge = "🟢 live LLM" if st.session_state.rule_source == "live-llm" else "🗄️ cached"
            st.caption(f"Structured rule  ·  source: {badge}")
            st.json(st.session_state.rule)
        else:
            st.info("Load a policy and click **Convert to rule** to see the structured output.")

#Tab 2: run
with tab2:
    st.subheader("Run the rule against claims")

    if not st.session_state.rule:
        st.info("Convert a policy in tab 1 first — then run it here.")
    else:
        rule = st.session_state.rule
        st.caption(f"Active rule: **{rule.get('name', rule.get('rule_id'))}**")
        results = engine.apply_rule(rule, claims)

        flagged = [r for r in results if r["matched"]]
        flagged_ids = {r["claim"]["claim_id"] for r in flagged}
        flagged_amount = sum(float(r["claim"]["billed_amount"]) for r in flagged)

        m1, m2, m3 = st.columns(3)
        m1.metric("Claims evaluated", len(results))
        m2.metric("Claims flagged", len(flagged))
        m3.metric("Billed $ flagged", f"${flagged_amount:,.2f}")

        def _highlight(row):
            hit = row["claim_id"] in flagged_ids
            return ["background-color: #fde2e1" if hit else "" for _ in row]

        st.dataframe(claims_df.style.apply(_highlight, axis=1),
                     use_container_width=True, hide_index=True)

        if flagged:
            st.markdown("**Flag detail**")
            st.table(pd.DataFrame([
                {"claim_id": r["claim"]["claim_id"], "action": r["action"], "reason": r["message"]}
                for r in flagged
            ]))

#Tab 3: compare
with tab3:
    st.subheader("Compare two versions of a policy")
    c1, c2 = st.columns(2)
    v1 = c1.selectbox("Version A", samples,
                      index=samples.index("mue_units_v1") if "mue_units_v1" in samples else 0)
    v2 = c2.selectbox("Version B", samples,
                      index=samples.index("mue_units_v2") if "mue_units_v2" in samples else 0)

    text_a = engine.load_sample_policy(v1)
    text_b = engine.load_sample_policy(v2)

    st.markdown("**Line-level diff**")
    st.code(engine.diff_policies(text_a, text_b, v1, v2) or "(files are identical)", language="diff")

    if st.button("🧠  Summarize the change"):
        try:
            summary, source = engine.summarize_change(text_a, text_b, cache_key=f"{v1}__{v2}")
            badge = "🟢 live LLM" if source == "live-llm" else "🗄️ cached"
            st.caption(f"Summary  ·  source: {badge}")
            st.success(summary)
        except Exception as exc:
            st.error(str(exc))

    cache_rules = engine._load_cache()["rules"]
    if v1 in cache_rules and v2 in cache_rules:
        st.markdown("**Impact on sample claims**")
        n_a = sum(1 for r in engine.apply_rule(cache_rules[v1], claims) if r["matched"])
        n_b = sum(1 for r in engine.apply_rule(cache_rules[v2], claims) if r["matched"])
        d1, d2 = st.columns(2)
        d1.metric(f"Flagged under {v1}", n_a)
        d2.metric(f"Flagged under {v2}", n_b, delta=n_b - n_a)